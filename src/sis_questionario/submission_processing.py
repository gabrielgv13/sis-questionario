"""Submission validation and scoring shared by the sync and async databases."""
from .profile_scoring import score_answers
from .scoring_rules import get_stored_rules


def score_submission(questionnaire, allowed_options, answers):
    allowed_pairs = {(row['id_pergunta'], row['id_opcao']) for row in allowed_options}
    question_ids = {question_id for question_id, _ in allowed_pairs}
    if not question_ids or set(answers) != question_ids or not allowed_pairs.issuperset(answers.items()):
        raise ValueError('Selecione uma opção válida para cada pergunta.')
    if not questionnaire['algoritmo']:
        return None

    answers_by_prompt = {
        row['enunciado']: row['texto']
        for row in allowed_options
        if answers[row['id_pergunta']] == row['id_opcao']
    }
    return score_answers(answers_by_prompt, get_stored_rules(questionnaire))
