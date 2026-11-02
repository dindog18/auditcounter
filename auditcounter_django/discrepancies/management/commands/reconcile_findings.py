from django.core.management.base import BaseCommand
from accounts_receivable.services.catalog import model


class Command(BaseCommand):
    help = 'Recalculate existing AP/AR cases and synchronize discrepancy history without changing source values.'

    def add_arguments(self, parser):
        parser.add_argument('--mode', choices=['ap','ar'])
        parser.add_argument('--case', type=int, dest='case_id')

    def handle(self, *args, **options):
        count = 0
        for mode in ([options['mode']] if options['mode'] else ['ap','ar']):
            cases = model(mode,'Transaction').objects.order_by('pk')
            if options['case_id'] is not None:
                cases = cases.filter(pk=options['case_id'])
            for case in cases.iterator():
                case.refresh_reconciliation_status()
                count += 1
        self.stdout.write(self.style.SUCCESS(f'Reconciled {count} cases.'))
