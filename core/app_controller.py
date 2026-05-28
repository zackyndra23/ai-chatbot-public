from fastapi import FastAPI
from starlette.middleware.wsgi import WSGIMiddleware
from modules.faq_automation.faq_controller import router as faq_router
from modules.chat_testing_ui.ctu_controller import flask_app
from modules.sales_slots_update import ssu_bp
from modules.late_response_followup import late_response_followup_bp


def register_blueprints(app: FastAPI):
    app.include_router(faq_router)
    app.mount("/ui", WSGIMiddleware(flask_app))

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.register_blueprint(ssu_bp)
    app.register_blueprint(late_response_followup_bp)