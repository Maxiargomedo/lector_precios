# Generated by Django 5.2.2 on 2025-07-25 22:16

import elFaro.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('elFaro', '0004_producto_precio_vecino'),
    ]

    operations = [
        migrations.AlterField(
            model_name='producto',
            name='precio',
            field=models.DecimalField(decimal_places=0, max_digits=7, validators=[elFaro.models.validate_price_value]),
        ),
        migrations.AlterField(
            model_name='producto',
            name='precio_vecino',
            field=models.DecimalField(blank=True, decimal_places=0, max_digits=7, null=True, validators=[elFaro.models.validate_price_value]),
        ),
    ]
