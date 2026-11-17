"""Versioned profile heuristic. Weights are keyed by question and option text."""
import json
from pathlib import Path

DEFAULT_SCORING_RULES = json.loads(Path(__file__).with_name('profile_scoring_v1.json').read_text(encoding='utf-8'))
DEFAULT_PROFILE_LABELS = DEFAULT_SCORING_RULES['profiles']
SCORING_VERSION = DEFAULT_SCORING_RULES['version']
LEGACY_SCORING_VERSION = 'perfil_sesi_v1'


def build_scoring_result(scores, strong_counts, rules=None):
    rules = DEFAULT_SCORING_RULES if rules is None else rules
    highest_score = max(scores.values())
    candidates = [profile for profile in rules['profiles'] if scores[profile] == highest_score]
    highest_strong_count = max(strong_counts[profile] for profile in candidates)
    winners = [profile for profile in candidates if strong_counts[profile] == highest_strong_count]
    return {
        'version': rules['version'],
        'scores': scores,
        'strong': strong_counts,
        'winners': winners,
        'category': winners[0] if len(winners) == 1 else 'misto',
    }


def score_answers(answers_by_question, rules=None):
    """Answers map question text to the selected option text, never DB IDs."""
    rules = DEFAULT_SCORING_RULES if rules is None else rules
    questions = rules['questions']
    profiles = rules['profiles']
    if set(answers_by_question) != {question['title'] for question in questions}:
        raise ValueError('As perguntas não correspondem à versão do classificador de perfil.')

    scores = dict.fromkeys(profiles, 0)
    strong_counts = dict.fromkeys(profiles, 0)
    for question in questions:
        selected_option = answers_by_question[question['title']]
        weights = question['options'].get(selected_option)
        if weights is None:
            raise ValueError('Alternativa sem regra de classificação.')
        for profile in profiles:
            added_points = weights['add'][profile]
            scores[profile] += added_points + weights['subtract'][profile]
            strong_counts[profile] += added_points == 20
    return build_scoring_result(scores, strong_counts, rules)
