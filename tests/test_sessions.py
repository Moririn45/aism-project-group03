"""Sessões completas (main.py) com o modelo falso: persistência entre execuções e falhas.

Cada chamada a main() cria objetos novos; a única coisa que passa de uma sessão para a
outra é o que está no disco. (O run_demo.py faz o mesmo com processos separados e o Ollama.)
"""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import main as tutor
from tests.fake_llm import FakeLLM

ROOT = Path(__file__).resolve().parent.parent
ANA = ROOT / "demo" / "aluno_ana.json"
ANA_STOPS = ROOT / "demo" / "aluno_ana_interrompe.json"


class Sessions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name) / "data"
        self.logs = Path(self.tmp.name) / "logs"

    def tearDown(self):
        self.tmp.cleanup()

    def run_session(self, student=ANA, llm=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = tutor.main(["--data-dir", str(self.data), "--log-dir", str(self.logs),
                               "--simulate", str(student)], llm=llm or FakeLLM())
        return code, out.getvalue()

    def profile(self):
        return json.loads((self.data / "profile.json").read_text(encoding="utf-8"))

    def last_plan(self):
        return [e for e in self.profile()["history"] if e["type"] == "plan"][-1]

    def test_session_3_reflects_session_1(self):
        topics = []
        for _ in range(3):
            code, _ = self.run_session()
            self.assertEqual(code, tutor.EXIT_OK)
            topics.append(self.last_plan()["topic"])
        self.assertEqual(topics, ["Equações", "Funções", "Frações"])
        self.assertEqual(self.last_plan()["mode"], "rever")
        self.assertEqual(self.profile()["session"], 4)
        for n in (1, 2, 3):
            self.assertTrue((self.logs / f"sessao_{n}.log").exists())

    def test_corruption_between_sessions(self):
        self.run_session(); self.run_session()
        (self.data / "profile.json").write_text('{"learner": "Ana", "ses', encoding="utf-8")
        code, out = self.run_session()
        self.assertEqual(code, tutor.EXIT_OK)
        self.assertIn("[recuperação]", out)
        self.assertEqual(self.last_plan()["topic"], "Frações")
        self.assertTrue((self.data / "profile.corrupt.json").exists())

    def test_profile_and_backup_deleted_between_sessions(self):
        self.run_session(); self.run_session()
        (self.data / "profile.json").unlink()
        (self.data / "profile.bak.json").unlink()
        code, out = self.run_session()
        self.assertEqual(code, tutor.EXIT_OK)
        self.assertIn("journal", out)
        self.assertEqual(self.last_plan()["topic"], "Frações")

    def test_model_failure_leaves_profile_untouched(self):
        self.run_session()
        before = (self.data / "profile.json").read_bytes()
        code, out = self.run_session(llm=FakeLLM(broken=True))
        self.assertEqual(code, tutor.EXIT_LESSON)
        self.assertIn("tentativa 3/3", out)
        self.assertEqual((self.data / "profile.json").read_bytes(), before)

    def test_model_unavailable_touches_nothing(self):
        code, out = self.run_session(llm=FakeLLM(unavailable=True))
        self.assertEqual(code, tutor.EXIT_NO_MODEL)
        self.assertFalse(self.data.exists())

    def test_interrupted_session_is_repeated(self):
        self.run_session()
        before = (self.data / "profile.json").read_bytes()
        code, _ = self.run_session(student=ANA_STOPS)
        self.assertEqual(code, tutor.EXIT_INTERRUPTED)
        self.assertEqual((self.data / "profile.json").read_bytes(), before)
        self.run_session()
        self.assertEqual(self.last_plan()["session"], 2)  # a sessão 2 foi repetida, não saltada


if __name__ == "__main__":
    unittest.main()
