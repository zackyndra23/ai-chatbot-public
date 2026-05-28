"""
Sales Slots Update (SSU) module initializer.

This package handles automated synchronization between MongoDB sales slot data
and a Google Sheet summary table that shows per-slot, per-day availability counts.

Exports:
    - ssu_bp: Flask blueprint for manual trigger endpoint.
    - SalesSlotsUpdateService: Main orchestration service.
    - register_ssu_scheduler: Background scheduler registration (APScheduler).

Usage:
    from modules.sales_slots_update import ssu_bp, register_ssu_scheduler
"""

from .ssu_controller import ssu_bp
from .ssu_service import SalesSlotsUpdateService
from .ssu_pipelines import register_ssu_scheduler