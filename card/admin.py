from django.contrib import admin

from .models import Card, Client


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ["name", "odoo_partner_id", "email_domains"]
    search_fields = ["name", "email_domains"]


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ["title", "source", "client", "column", "urgency", "ai_assist_score", "last_activity_at"]
    list_filter = ["source", "column", "urgency", "client"]
    search_fields = ["title", "excerpt", "external_id"]
    raw_id_fields = ["client", "connection"]
