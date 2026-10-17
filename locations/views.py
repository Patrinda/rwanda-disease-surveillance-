from django.db.models import Count, Q
from django.views.generic import DetailView, ListView

from accounts.permissions import RoleRequiredMixin
from surveillance.analytics import district_context

from .models import District, Province


class DistrictListView(RoleRequiredMixin, ListView):
    model = District
    template_name = "locations/district_list.html"
    context_object_name = "districts"

    def get_queryset(self):
        qs = District.objects.select_related("province").annotate(
            case_total=Count("cases", distinct=True),
            active_total=Count("cases", filter=Q(cases__status="active"), distinct=True),
        )
        province = self.request.GET.get("province", "")
        if province.isdigit():
            qs = qs.filter(province_id=province)
        return qs.order_by("province__name", "name")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["provinces"] = Province.objects.all()
        ctx["selected_province"] = self.request.GET.get("province", "")
        return ctx


class DistrictDetailView(RoleRequiredMixin, DetailView):
    model = District
    template_name = "locations/district_detail.html"
    context_object_name = "district"

    def get_queryset(self):
        return District.objects.select_related("province")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(district_context(self.object))
        return ctx
