"""Regras do Planeador (não precisam do modelo)."""
import copy
import unittest

from agents.planner import choose_topic, sessions_counted

ORDER = ["Números inteiros", "Frações", "Equações", "Funções", "Percentagens"]


def profile(session, **topics):
    base = {name: {"status": None, "last_seen": None} for name in ORDER}
    for key, (status, seen) in topics.items():
        base[key.replace("_", " ")] = {"status": status, "last_seen": seen}
    return {"session": session, "topics": base}


class PlannerRules(unittest.TestCase):
    def test_sessions_counted_includes_both_ends(self):
        self.assertEqual(sessions_counted(3, 1), 3)
        self.assertEqual(sessions_counted(2, 1), 2)

    def test_figure2_sequence(self):
        """Sessão 1 avança para Equações, a 2 para Funções e a 3 revê Frações."""
        s1 = profile(1, Números_inteiros=("solid", 1), Frações=("weak", 1))
        self.assertEqual(choose_topic(s1, ORDER)["topic"], "Equações")
        s2 = profile(2, Números_inteiros=("solid", 1), Frações=("weak", 1), Equações=("improving", 1))
        d2 = choose_topic(s2, ORDER)
        self.assertEqual((d2["topic"], d2["mode"]), ("Funções", "avancar"))
        self.assertIn("revejo-o na sessão 3", d2["reason"])
        s3 = profile(3, Números_inteiros=("solid", 1), Frações=("weak", 1), Equações=("improving", 1),
                     Funções=("improving", 2))
        d3 = choose_topic(s3, ORDER)
        self.assertEqual((d3["topic"], d3["mode"]), ("Frações", "rever"))
        self.assertTrue(d3["reason"].startswith("Revejo Frações"))

    def test_most_overdue_weak_topic_first(self):
        p = profile(6, Números_inteiros=("weak", 3), Frações=("weak", 2), Equações=("solid", 4))
        self.assertEqual(choose_topic(p, ORDER)["topic"], "Frações")

    def test_practice_when_everything_was_seen(self):
        p = profile(9, Números_inteiros=("solid", 1), Frações=("improving", 3), Equações=("improving", 5),
                    Funções=("solid", 6), Percentagens=("solid", 8))
        d = choose_topic(p, ORDER)
        self.assertEqual((d["topic"], d["mode"]), ("Frações", "praticar"))

    def test_consolidate_when_everything_is_solid(self):
        p = profile(9, Números_inteiros=("solid", 4), Frações=("solid", 2), Equações=("solid", 5),
                    Funções=("solid", 6), Percentagens=("solid", 8))
        d = choose_topic(p, ORDER)
        self.assertEqual((d["topic"], d["mode"]), ("Frações", "consolidar"))

    def test_planner_never_changes_the_profile(self):
        p = profile(3, Frações=("weak", 1))
        before = copy.deepcopy(p)
        choose_topic(p, ORDER)
        self.assertEqual(p, before)


if __name__ == "__main__":
    unittest.main()
