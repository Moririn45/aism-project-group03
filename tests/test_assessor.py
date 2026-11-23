"""Correção de respostas, classificação dos tópicos e regra de escrita do Avaliador."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from agents.assessor import Assessor, classify_diagnostic, classify_lesson, same_answer
from agents.messages import ACLMessage
from agents.planner import Planner
from agents.teacher import Teacher
from curriculum import load_curriculum
from profile_store import ProfileStore
from tests.fake_llm import FakeLLM


class Answers(unittest.TestCase):
    def test_equivalent_numbers(self):
        for expected, given in [("3/4", "0,75"), ("3/4", "0.75"), ("3/4", "x = 3/4"), ("6", "6.0"),
                                ("1/3", "0,33"), ("25%", "25"), ("-2", "−2"), ("12 cm", "12"), ("5", " 5. ")]:
            self.assertTrue(same_answer(expected, given), (expected, given))

    def test_different_numbers(self):
        for expected, given in [("5", "4"), ("1/3", "0,3"), ("3/4", "4/3"), ("-2", "2")]:
            self.assertFalse(same_answer(expected, given), (expected, given))

    def test_text_needs_the_model(self):
        self.assertIsNone(same_answer("3/4", "três quartos"))


class Classification(unittest.TestCase):
    def test_diagnostic(self):
        self.assertEqual([classify_diagnostic(s, 2) for s in (0, 1, 2)], ["weak", "improving", "solid"])

    def test_lesson_needs_two_sessions_to_be_solid(self):
        self.assertEqual(classify_lesson(None, 2, 2), "improving")
        self.assertEqual(classify_lesson("weak", 2, 2), "improving")
        self.assertEqual(classify_lesson("improving", 2, 2), "solid")
        self.assertEqual(classify_lesson("solid", 1, 2), "improving")
        self.assertEqual(classify_lesson("improving", 0, 2), "weak")


class ScriptedStudent:
    name, subject, session = "Teste", "matematica", 1

    def __init__(self, answers):
        self.answers = list(answers)

    def answer(self, question, topic, phase, index):
        return self.answers.pop(0)


class AssessorAgent(unittest.TestCase):
    def setUp(self):
        self.quiet = contextlib.redirect_stdout(io.StringIO())   # esconde o texto dos agentes
        self.quiet.__enter__()
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ProfileStore(self.tmp.name)
        self.llm = FakeLLM()
        self.cur = load_curriculum("matematica")
        self.assessor = Assessor(self.store, self.llm, self.cur)

    def tearDown(self):
        self.tmp.cleanup()
        self.quiet.__exit__(None, None, None)

    def test_only_the_assessor_gets_the_store(self):
        self.assertIs(self.assessor.store, self.store)
        self.assertFalse(hasattr(Planner(self.cur), "store"))
        self.assertFalse(hasattr(Teacher(self.llm, self.cur), "store"))

    def test_diagnose_creates_and_saves_profile(self):
        profile = self.assessor.diagnose(ScriptedStudent(["5", "24", "não sei", "7"]), "Teste")
        self.assertEqual(profile["topics"]["Números inteiros"], {"status": "solid", "last_seen": 1})
        self.assertEqual(profile["topics"]["Frações"], {"status": "weak", "last_seen": 1})
        self.assertEqual(self.llm.calls, 0)          # respostas numéricas: sem chamadas ao modelo
        saved = json.loads(Path(self.tmp.name, "profile.json").read_text(encoding="utf-8"))
        self.assertIsNone(ProfileStore.problem_with(saved))

    def test_assess_updates_topic_and_session(self):
        profile = self.assessor.diagnose(ScriptedStudent(["5", "24", "0", "0"]), "Teste")
        request = ACLMessage("REQUEST", "teacher", "assessor",
                             {"topic": "Equações", "mode": "avancar", "reason": "teste",
                              "questions": [{"enunciado": "a", "resposta": "3/4"},
                                            {"enunciado": "b", "resposta": "12"}],
                              "answers": ["três quartos", "12"], "attempts": 1})
        reply = self.assessor.assess(request, profile)
        self.assertEqual(reply.performative, "INFORM")
        self.assertEqual(reply.content["score"], 2)       # "três quartos" foi aceite pelo modelo
        self.assertEqual(profile["topics"]["Equações"], {"status": "improving", "last_seen": 1})
        self.assertEqual(profile["session"], 2)
        self.assertEqual([e["type"] for e in profile["history"]],
                         ["start", "diagnostic", "plan", "assessment", "session_end"])

    def test_rejects_message_for_another_agent(self):
        wrong = ACLMessage("INFORM", "planner", "teacher", {"topic": "Equações", "mode": "avancar"})
        with self.assertRaises(ValueError):
            self.assessor.assess(wrong, {})


if __name__ == "__main__":
    unittest.main()
