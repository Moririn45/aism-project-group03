"""Persistência e recuperação do perfil (escrita atómica, checksum, backup e journal)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import profile_store
from profile_store import ProfileStore, StoreError, apply_event, replay


def build_profile(sessions=2):
    """Perfil de exemplo, construído com eventos, como faz o Avaliador."""
    events = [
        {"seq": 1, "type": "start", "learner": "Ana", "subject": "Matemática", "subject_file": "matematica",
         "topics": ["Frações", "Equações", "Funções"]},
        {"seq": 2, "type": "diagnostic", "session": 1,
         "results": {"Frações": {"score": 0, "of": 2, "status": "weak"}}},
    ]
    for s, topic in zip(range(1, sessions + 1), ["Equações", "Funções"]):
        events.append({"seq": len(events) + 1, "type": "assessment", "session": s, "topic": topic,
                       "score": 2, "of": 2, "old_status": None, "new_status": "improving"})
        events.append({"seq": len(events) + 1, "type": "session_end", "session": s})
    return replay(events)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.store = ProfileStore(self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def save_two_versions(self):
        """Grava a sessão 1 e depois a sessão 2 (o backup fica com a sessão 1)."""
        self.store.save(build_profile(1))
        self.store.save(build_profile(2))
        return build_profile(2)

    def assert_same_state(self, a, b):
        self.assertEqual((a["session"], a["topics"]), (b["session"], b["topics"]))


class SaveAndLoad(StoreTest):
    def test_roundtrip(self):
        expected = self.save_two_versions()
        loaded = ProfileStore(self.dir).load()
        self.assert_same_state(loaded, expected)
        self.assertTrue(loaded["checksum"].startswith("sha256:"))

    def test_backup_keeps_previous_version(self):
        self.save_two_versions()
        backup = json.loads((self.dir / "profile.bak.json").read_text(encoding="utf-8"))
        self.assertEqual(backup["session"], 2)          # versão gravada no fim da sessão 1
        self.assertEqual(json.loads((self.dir / "profile.json").read_text(encoding="utf-8"))["session"], 3)

    def test_journal_has_every_event(self):
        p = self.save_two_versions()
        lines = (self.dir / "history.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line) for line in lines], p["history"])

    def test_replay_gives_the_same_profile(self):
        p = build_profile(2)
        self.assertEqual(replay(p["history"])["topics"], p["topics"])

    def test_no_files_means_new_student(self):
        self.assertIsNone(self.store.load())
        self.assertEqual(self.store.notes, [])


class Recovery(StoreTest):
    def test_corrupted_file_is_isolated_and_restored(self):
        expected = self.save_two_versions()
        path = self.dir / "profile.json"
        path.write_text(path.read_text(encoding="utf-8")[:120], encoding="utf-8")   # corta o ficheiro a meio
        store = ProfileStore(self.dir)
        loaded = store.load()
        self.assert_same_state(loaded, expected)          # backup + eventos do journal: nada se perde
        self.assertTrue((self.dir / "profile.corrupt.json").exists())
        self.assertTrue(any("isolado" in n for n in store.notes))

    def test_tampered_file_fails_checksum(self):
        expected = self.save_two_versions()
        path = self.dir / "profile.json"
        path.write_text(path.read_text(encoding="utf-8").replace('"weak"', '"solid"'), encoding="utf-8")
        store = ProfileStore(self.dir)
        loaded = store.load()
        self.assertEqual(loaded["topics"]["Frações"]["status"], "weak")
        self.assert_same_state(loaded, expected)
        self.assertIn("checksum", store.notes[0])

    def test_deleted_file_is_restored_from_backup(self):
        expected = self.save_two_versions()
        (self.dir / "profile.json").unlink()
        self.assert_same_state(ProfileStore(self.dir).load(), expected)

    def test_deleted_file_and_backup_rebuilt_from_journal(self):
        expected = self.save_two_versions()
        (self.dir / "profile.json").unlink()
        (self.dir / "profile.bak.json").unlink()
        store = ProfileStore(self.dir)
        self.assert_same_state(store.load(), expected)
        self.assertIn("journal", store.notes[-1])
        self.assertTrue((self.dir / "profile.json").exists())   # o perfil reconstruído foi gravado

    def test_backup_only_when_journal_is_also_lost(self):
        self.save_two_versions()
        (self.dir / "profile.json").unlink()
        (self.dir / "history.jsonl").unlink()
        loaded = ProfileStore(self.dir).load()
        self.assertEqual(loaded["session"], 2)            # perde-se só o último passo gravado

    def test_everything_corrupted_means_new_diagnostic(self):
        self.save_two_versions()
        for name in ("profile.json", "profile.bak.json", "history.jsonl"):
            (self.dir / name).write_text("lixo", encoding="utf-8")
        store = ProfileStore(self.dir)
        self.assertIsNone(store.load())
        self.assertIn("diagnóstico", store.notes[-1])
        for name in ("profile.corrupt.json", "profile.bak.corrupt.json"):
            self.assertTrue((self.dir / name).exists())   # os ficheiros estragados nunca se apagam

    def test_second_corruption_does_not_overwrite_the_first(self):
        self.save_two_versions()
        for _ in range(2):
            (self.dir / "profile.json").write_text("{", encoding="utf-8")
            ProfileStore(self.dir).load()
        self.assertTrue((self.dir / "profile.corrupt.json").exists())
        self.assertTrue((self.dir / "profile.corrupt-1.json").exists())

    def test_torn_journal_line_is_ignored_and_repaired(self):
        self.save_two_versions()
        with open(self.dir / "history.jsonl", "a", encoding="utf-8") as f:
            f.write('{"seq": 99, "type": "assess')            # linha cortada por uma falha
        loaded = ProfileStore(self.dir).load()
        lines = (self.dir / "history.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), len(loaded["history"]))
        self.assertTrue((self.dir / "history.corrupt.jsonl").exists())


class CrashSafety(StoreTest):
    def test_crash_before_rename_keeps_old_file(self):
        self.save_two_versions()
        before = (self.dir / "profile.json").read_text(encoding="utf-8")
        real_replace = profile_store.os.replace

        def failing_replace(src, dst):
            if Path(dst).name == "profile.json":
                raise OSError("falha simulada a meio da gravação")
            return real_replace(src, dst)

        with mock.patch.object(profile_store.os, "replace", side_effect=failing_replace):
            with self.assertRaises(StoreError):
                self.store.save(build_profile(2))
        self.assertEqual((self.dir / "profile.json").read_text(encoding="utf-8"), before)
        store = ProfileStore(self.dir)
        self.assertIsNotNone(store.load())               # continua válido
        self.assertTrue(any(".tmp" in n for n in store.notes))
        self.assertFalse(list(self.dir.glob("*.tmp")))

    def test_file_broken_during_session_does_not_go_to_backup(self):
        self.save_two_versions()
        store = ProfileStore(self.dir)
        profile = store.load()
        good_backup = (self.dir / "profile.bak.json").read_text(encoding="utf-8")
        (self.dir / "profile.json").write_text("estragado a meio da sessão", encoding="utf-8")
        profile = apply_event(profile, {"seq": len(profile["history"]) + 1, "type": "session_end",
                                        "session": profile["session"]})
        store.save(profile)
        self.assertEqual((self.dir / "profile.bak.json").read_text(encoding="utf-8"), good_backup)
        self.assertTrue((self.dir / "profile.corrupt.json").exists())
        self.assertIsNotNone(ProfileStore(self.dir).load())


if __name__ == "__main__":
    unittest.main()
