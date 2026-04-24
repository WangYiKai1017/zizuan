from .base import PromptTemplate
from .question_prompts import TEMPLATES as QUESTION_TEMPLATES
from .emotion_prompts import TEMPLATES as EMOTION_TEMPLATES
from .summary_prompts import TEMPLATES as SUMMARY_TEMPLATES

# 合并所有模板
TEMPLATES = {}
TEMPLATES.update(QUESTION_TEMPLATES)
TEMPLATES.update(EMOTION_TEMPLATES)
TEMPLATES.update(SUMMARY_TEMPLATES)

__all__ = ["PromptTemplate", "TEMPLATES"]