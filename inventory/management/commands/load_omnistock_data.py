import os
from pathlib import Path
from django.core.management.base import BaseCommand
from inventory.utils import import_omnistock_csv

class Command(BaseCommand):
    help = 'Loads inventory data from OmniStock CSV file'

    def add_arguments(self, parser):
        parser.add_argument('--path', type=str, help='Path to OmniStock CSV file')

    def handle(self, *args, **options):
        file_path = options.get('path')
        if not file_path:
            downloads_dir = Path.home() / 'Downloads'
            candidates = list(downloads_dir.glob('omnistock-inventory-stock*.csv')) or list(downloads_dir.glob('*omnistock*.csv'))
            if candidates:
                file_path = str(candidates[0])
            else:
                self.stderr.write(self.style.ERROR("No OmniStock CSV found in Downloads. Specify path with --path"))
                return

        self.stdout.write(f"Importing OmniStock inventory from: {file_path}")
        with open(file_path, 'r', encoding='utf-8-sig', errors='replace') as f:
            created, updated, errors = import_omnistock_csv(f)

        self.stdout.write(self.style.SUCCESS(f"Successfully processed: {created} created, {updated} updated."))
        if errors:
            self.stdout.write(self.style.WARNING(f"Encountered {len(errors)} warnings/errors:"))
            for err in errors[:5]:
                self.stdout.write(f" - {err}")
