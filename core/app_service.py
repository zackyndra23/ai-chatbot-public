from types import SimpleNamespace
from infra.app_repo import build_faq_repo
from core.app_pipelines import build_pipelines
from modules.faq_automation.faq_service import FAQService

def build_services(cfg):
    faq_repo = build_faq_repo(cfg)
    pipes = build_pipelines(cfg)
    faq = FAQService(cfg, faq_repo, pipes)
    return SimpleNamespace(faq=faq)
