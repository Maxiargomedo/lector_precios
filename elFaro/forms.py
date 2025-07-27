from django import forms
from .models import Producto
import re

class ProductoForm(forms.ModelForm):
    class Meta:
        model = Producto
        fields = '__all__'

    def clean_codigo_barras(self):
        codigo = self.cleaned_data['codigo_barras']
        return re.sub(r'[\s\r\n\t]+', '', codigo)