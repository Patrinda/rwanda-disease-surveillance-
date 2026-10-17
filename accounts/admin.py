from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    extra = 0


class UserAdmin(BaseUserAdmin):
    inlines = [UserProfileInline]
    list_display = ("username", "email", "first_name", "last_name", "district", "role_names", "is_staff")
    list_select_related = ("profile__district",)

    @admin.display(description="District")
    def district(self, obj):
        return obj.profile.district if hasattr(obj, "profile") else "-"

    @admin.display(description="Roles")
    def role_names(self, obj):
        return ", ".join(obj.groups.values_list("name", flat=True)) or "-"


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "district", "job_title", "phone")
    list_filter = ("district__province",)
    search_fields = ("user__username", "job_title")
