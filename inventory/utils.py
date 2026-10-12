import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from decimal import Decimal
from datetime import datetime
from django.utils import timezone
from .models import Product, Brand, Category, StockMovement, ProductIMEI, Supplier

def clean_value(val):
    if not val:
        return ""
    val = str(val).strip()
    if val.startswith('="') and val.endswith('"'):
        val = val[2:-1]
    return val

def parse_decimal(val, default=Decimal('0.00')):
    try:
        cleaned = clean_value(val).replace(',', '').replace('₹', '').strip()
        if not cleaned:
            return default
        return Decimal(cleaned)
    except Exception:
        return default

def parse_int(val, default=0):
    try:
        cleaned = clean_value(val).replace(',', '').strip()
        if not cleaned:
            return default
        return int(float(cleaned))
    except Exception:
        return default

def parse_date(val):
    cleaned = clean_value(val)
    if not cleaned:
        return timezone.now().date()
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%m/%d/%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            pass
    return timezone.now().date()

def read_xlsx_rows(file_bytes):
    """Parses Excel (.xlsx) sheets into a list of row dicts using standard zipfile XML."""
    with zipfile.ZipFile(io.BytesIO(file_bytes), 'r') as z:
        strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            tree = ET.fromstring(z.read('xl/sharedStrings.xml'))
            for si in tree.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si'):
                text = ''.join(t.text for t in si.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t') if t.text)
                strings.append(text)
        
        sheet_tree = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        rows = sheet_tree.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheetData/{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row')
        all_rows = []
        for r in rows:
            row_vals = []
            for c in r.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c'):
                t = c.get('t')
                v = c.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
                if v is not None and v.text:
                    if t == 's':
                        idx = int(v.text)
                        row_vals.append(strings[idx] if idx < len(strings) else "")
                    else:
                        row_vals.append(v.text)
                else:
                    row_vals.append("")
            if any(row_vals):
                all_rows.append(row_vals)
        return all_rows

def import_omnistock_file(file_obj, filename="", user=None):
    """
    Unified importer for:
    1. Standard OmniStock Inventory CSV & Template CSV
    2. OmniStock Excel Restock Template (.xlsx)
    3. Refurbished Stock sheets with Grade, RAM/ROM, Brand Box (.xlsx / .csv)
    4. Buyback Stock sheets with IMEI, WSN NO, Tracking ID (.xlsx / .csv)
    5. NTC Stock sheets with IMEI, Tracking ID (.xlsx / .csv)
    """
    if hasattr(file_obj, 'read'):
        raw_bytes = file_obj.read()
    elif isinstance(file_obj, bytes):
        raw_bytes = file_obj
    else:
        raw_bytes = str(file_obj).encode('utf-8')

    is_xlsx = filename.lower().endswith('.xlsx') or raw_bytes[:4] == b'PK\x03\x04'

    if is_xlsx:
        rows = read_xlsx_rows(raw_bytes)
        if not rows:
            return 0, 0, ["Empty Excel sheet"]
        # Find header row
        header_idx = 0
        for i, row in enumerate(rows[:5]):
            row_str = " ".join(str(c).lower() for c in row)
            if any(k in row_str for k in ['sku', 'product', 'brand', 'model', 'imei', 'tracking']):
                header_idx = i
                break
        headers = [str(c).strip() for c in rows[header_idx]]
        data_rows = []
        for r in rows[header_idx + 1:]:
            d = {}
            for h, val in zip(headers, r):
                if h:
                    d[h] = val
            data_rows.append(d)
    else:
        text = raw_bytes.decode('utf-8-sig', errors='replace')
        reader = csv.DictReader(io.StringIO(text))
        data_rows = list(reader)

    created_count = 0
    updated_count = 0
    errors = []

    for idx, row in enumerate(data_rows, start=2):
        try:
            # Detect row fields flexibly
            name = clean_value(row.get('Product Name') or row.get('ProductName') or row.get('Model') or row.get('MODEL') or '')
            brand_name = clean_value(row.get('Brand') or row.get('BRAND') or '')
            cat_name = clean_value(row.get('Category') or '')
            sku = clean_value(row.get('SKU') or row.get('TD ID') or row.get('Tracking id') or row.get('Tracking ID') or '')
            barcode = clean_value(row.get('Barcode') or row.get('WSN NO') or '')
            
            # Specs
            ram_rom = clean_value(row.get('RAM|ROM') or '')
            ram = clean_value(row.get('RAM') or '')
            rom = clean_value(row.get('ROM') or '')
            if ram_rom and '|' in ram_rom:
                ram, rom = [x.strip() for x in ram_rom.split('|', 1)]
            
            color = clean_value(row.get('Color') or '')
            grade = clean_value(row.get('Grade') or row.get('Granularity') or 'N/A')
            box_condition = clean_value(row.get('Brand Box') or '')
            tracking_id = clean_value(row.get('Tracking ID') or row.get('Tracking id') or '')
            wsn_no = clean_value(row.get('WSN NO') or '')
            imei_num = clean_value(row.get('IMEI') or row.get('IMEI1') or '')

            # Pricing & Quantity
            qty = parse_int(row.get('Stock Quantity') or row.get('Quantity') or row.get('RestockQuantity') or row.get('Qty') or 1, default=1)
            cost = parse_decimal(row.get('Unit Cost (₹)') or row.get('Unit Cost') or row.get('PurchasePrice') or row.get('P2P Price') or row.get('PRICE') or 0)
            price = parse_decimal(row.get('Selling Price (₹)') or row.get('Selling Price') or row.get('SellingPrice') or row.get('RSP') or (cost * Decimal('1.25') if cost > 0 else 0))
            mrp = parse_decimal(row.get('MRP (₹)') or row.get('MRP') or price)
            
            condition = clean_value(row.get('Condition') or ('Refurbished' if grade != 'N/A' else 'New'))
            status = clean_value(row.get('Status') or 'Ready to Sell')
            warehouse = clean_value(row.get('Warehouse / Location') or row.get('Warehouse/Location') or 'Main Warehouse (Central)')
            lot_id = clean_value(row.get('Lot ID') or '')
            notes = clean_value(row.get('Notes') or '')

            if not name and not sku and not imei_num:
                continue

            if not sku:
                if imei_num:
                    sku = f"IMEI-{imei_num[-8:]}"
                elif tracking_id:
                    sku = f"TRK-{tracking_id}"
                else:
                    sku = f"SKU-{idx:05d}"

            if not name:
                name = f"{brand_name} {sku}".strip()

            brand = None
            if brand_name:
                brand, _ = Brand.objects.get_or_create(name=brand_name)

            category = None
            if not cat_name:
                cat_name = 'Smartphones & Tablets' if (ram or rom or imei_num) else 'Electronics'
            if cat_name:
                category, _ = Category.objects.get_or_create(name=cat_name)

            product, created = Product.objects.get_or_create(
                sku=sku,
                defaults={
                    'name': name,
                    'barcode': barcode,
                    'brand': brand,
                    'category': category,
                    'model_name': name,
                    'ram': ram,
                    'rom': rom,
                    'color': color,
                    'grade': grade if grade in ['A1', 'A2', 'A3', 'B', 'C'] else 'N/A',
                    'box_condition': box_condition,
                    'tracking_id': tracking_id,
                    'wsn_no': wsn_no,
                    'lot_id': lot_id,
                    'condition': condition,
                    'status': status,
                    'warehouse_location': warehouse,
                    'quantity': qty,
                    'unit_cost': cost,
                    'selling_price': price,
                    'mrp': mrp,
                    'notes': notes,
                }
            )

            if created:
                created_count += 1
                if qty > 0:
                    StockMovement.objects.create(
                        product=product,
                        movement_type='intake',
                        quantity=qty,
                        previous_quantity=0,
                        new_quantity=qty,
                        reference='Import Intake',
                        user=user,
                        notes=f'Imported from {filename or "dataset"}'
                    )
            else:
                updated_count += 1
                if cost > 0:
                    product.unit_cost = cost
                if price > 0:
                    product.selling_price = price
                if ram: product.ram = ram
                if rom: product.rom = rom
                if color: product.color = color
                if tracking_id: product.tracking_id = tracking_id
                product.save()

            # Attach IMEI if present
            if imei_num and not ProductIMEI.objects.filter(imei1=imei_num).exists():
                ProductIMEI.objects.create(
                    product=product,
                    imei1=imei_num,
                    status='AVAILABLE'
                )

        except Exception as e:
            errors.append(f"Row {idx}: {str(e)}")

    return created_count, updated_count, errors

def import_omnistock_csv(file_stream, user=None):
    """Backward compatibility wrapper"""
    return import_omnistock_file(file_stream, filename="import.csv", user=user)
