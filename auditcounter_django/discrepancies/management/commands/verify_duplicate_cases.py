"""Report historical exact duplicates without modifying records."""
import json
from django.core.management.base import BaseCommand
from accounts_receivable.services.case_duplicates import historical_duplicates

class Command(BaseCommand):
    help='Report historical identical AP/AR case groups as JSON lines; no writes.'
    def add_arguments(self,parser):
        parser.add_argument('--module',choices=['ap','ar'])
    def handle(self,*args,**options):
        for mode in ([options['module']] if options.get('module') else ['ap','ar']):
            for group in historical_duplicates(mode): self.stdout.write(json.dumps(group))
