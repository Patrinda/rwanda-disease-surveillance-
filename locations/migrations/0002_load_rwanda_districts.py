"""Data migration: create the 5 provinces and 30 districts of Rwanda.

The names and centre points come from locations/data/districts.json, which is
produced from the district shapefile by tools/build_geojson.py.
"""
import json
from pathlib import Path

from django.db import migrations


def load_districts(apps, schema_editor):
    Province = apps.get_model("locations", "Province")
    District = apps.get_model("locations", "District")
    path = Path(__file__).resolve().parent.parent / "data" / "districts.json"
    for row in json.loads(path.read_text(encoding="utf-8")):
        province, _ = Province.objects.get_or_create(name=row["province"])
        District.objects.get_or_create(
            name=row["name"],
            defaults={"province": province, "latitude": row["latitude"], "longitude": row["longitude"]},
        )


def remove_districts(apps, schema_editor):
    apps.get_model("locations", "District").objects.all().delete()
    apps.get_model("locations", "Province").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [("locations", "0001_initial")]

    operations = [migrations.RunPython(load_districts, remove_districts)]
