from django import forms
from .models import Product, StockMovement, Category, Brand

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            'name', 'product_code', 'sku', 'barcode', 'brand', 'category',
            'lot_id', 'condition', 'status', 'warehouse_location',
            'received_date', 'quantity', 'stock_unit',
            'unit_cost', 'selling_price', 'mrp', 'gst_scheme',
            'min_stock_alert_level', 'image_url', 'notes'
        ]
        widgets = {
            'received_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

class StockAdjustmentForm(forms.Form):
    delta = forms.IntegerField(
        label="Adjustment Amount",
        help_text="Positive number to add stock, negative number to remove stock."
    )
    movement_type = forms.ChoiceField(
        choices=[
            ('adjustment', 'Manual Adjustment'),
            ('intake', 'Additional Intake'),
            ('damaged', 'Damaged / Write-off'),
            ('return', 'Customer Return')
        ]
    )
    notes = forms.CharField(widget=forms.Textarea(attrs={'rows': 2}), required=False)

class CSVImportForm(forms.Form):
    csv_file = forms.FileField(label="Select OmniStock CSV File")
