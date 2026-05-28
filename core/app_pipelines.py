from types import SimpleNamespace
from modules.faq_automation import faq_pipelines as pipes
from modules.late_response_followup.lrf_pipelines import register_late_response_followup_job


def build_pipelines(cfg):
    return SimpleNamespace(
        build_text=lambda: pipes.build_text(cfg),
        chunk=pipes.chunk,
        save_latest=pipes.save_latest,
    )


def register_background_jobs(scheduler):
    register_late_response_followup_job(scheduler)