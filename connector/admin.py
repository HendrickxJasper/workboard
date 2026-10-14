from django.contrib import admin

from .models import Connection


@admin.register(Connection)
class ConnectionAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "is_active", "last_sync_at", "last_error"]
    list_filter = ["kind", "is_active"]
    search_fields = ["name"]
