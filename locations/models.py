from django.db import models


class Province(models.Model):
    name = models.CharField(max_length=60, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class District(models.Model):
    province = models.ForeignKey(Province, on_delete=models.PROTECT, related_name="districts")
    name = models.CharField(max_length=80, unique=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
