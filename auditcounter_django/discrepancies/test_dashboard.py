from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from accounts_receivable.services.catalog import model,party_key
from .models import DiscrepancyFinding,CaseInvestigation

class DashboardTests(TestCase):
    def setUp(self):
        self.cases=[]
        for mode,currency in [('ap','PHP'),('ar','USD')]:
            key=party_key(mode)
            party=model(mode,key).objects.create(**{key+'_code':mode,key+'_name':mode+' Trading'})
            case=model(mode,'Transaction').objects.create(pk=1000001,**{key:party},transaction_date='2026-11-02',currency=currency)
            type(case).objects.filter(pk=case.pk).update(reconciliation_status='exception',total_discrepancy_amount=10)
            self.cases.append(case)
            for n,severity in enumerate(['warning','critical']):
                DiscrepancyFinding.objects.create(**{mode+'_transaction':case},fingerprint=str(n),finding_code='PRICE_VARIANCE',severity=severity,summary='Difference',difference_amount=10,first_detected_at=timezone.now(),last_detected_at=timezone.now())
        CaseInvestigation.objects.create(ar_transaction=self.cases[1],workflow_status='resolved',closed_at=timezone.now(),review_required=True)

    def get(self,params=None):
        response=self.client.get('/discrepancies/api/cases/',params or {})
        self.assertEqual(response.status_code,200,response.content)
        return response.json()

    def test_combines_without_duplicate_ids_or_financial_double_counting(self):
        data=self.get()
        self.assertEqual(data['count'],2)
        self.assertEqual({row['case_key'] for row in data['results']},{f'ap:{self.cases[0].pk}',f'ar:{self.cases[1].pk}'})
        self.assertEqual({row['party_name'] for row in data['results']},{'ap Trading','ar Trading'})
        for row in data['results']:
            self.assertEqual(row['open_findings_count'],2)
            self.assertEqual(row['highest_severity'],'critical')
            self.assertEqual(row['discrepancy_amount'],'10.00')
        totals=self.client.get('/discrepancies/api/summary/').json()
        self.assertEqual(totals['total'],2)
        self.assertEqual(totals['resolved'],1)
        self.assertEqual(totals['renewed_review'],1)
        self.assertEqual({(r['module'],r['currency'],float(r['amount'])) for r in totals['financial']},{('ap','PHP',10),('ar','USD',10)})
        self.assertEqual(next(r for r in data['results'] if r['module']=='ar')['reconciliation_status'],'exception')

    def test_filters(self):
        for params,count in [({'module':'ap'},1),({'investigation_status':'not_started'},1),({'investigation_status':'resolved'},1),({'reconciliation_status':'matched'},0),({'severity':'critical'},2),({'severity':'warning'},0),({'currency':'USD'},1),({'q':'ap Trading'},1),({'q':f'AR-{self.cases[1].pk}'},1),({'date_from':'2026-11-03'},0),({'date_to':'2026-11-01'},0)]:
            with self.subTest(params=params): self.assertEqual(self.get(params)['count'],count)
        self.assertEqual(self.client.get('/discrepancies/api/summary/',{'module':'ap'}).json()['total'],1)

    def test_pagination_and_validation(self):
        first=self.get({'page_size':1});second=self.get({'page_size':1,'page':2})
        self.assertNotEqual(first['results'][0]['case_key'],second['results'][0]['case_key'])
        self.assertEqual(first,self.get({'page_size':1}))
        self.assertEqual(self.get({'page':999})['results'],[])
        for params in ({'module':'xx'},{'page':0},{'page_size':101},{'sort':'password'},{'date_from':'wrong'},{'date_from':'2027-01-01','date_to':'2026-01-01'},{'currency':'php'},{'unexpected':'x'}):
            self.assertEqual(self.client.get('/discrepancies/api/cases/',params).status_code,400)
        for sort in ('party_name','-discrepancy_amount','highest_severity','reference'):
            self.assertEqual(self.get({'sort':sort})['count'],2)

    def test_read_only_bounded_queries_and_existing_links(self):
        from django.db import connection
        def guard(execute,sql,params,many,context):
            self.assertTrue(sql.lstrip(' (\n\t').upper().startswith('SELECT'),sql)
            return execute(sql,params,many,context)
        with connection.execute_wrapper(guard),patch('discrepancies.services.refresh_transaction',side_effect=AssertionError('No recalculation')):
            with self.assertNumQueries(2): data=self.get()
            self.assertEqual(self.client.get('/discrepancies/').status_code,200)
            self.assertEqual(self.client.get('/discrepancies/api/summary/').status_code,200)
        for row in data['results']: self.assertEqual(self.client.get(row['detail_url']).status_code,200)
        self.assertEqual(self.client.post('/discrepancies/api/cases/').status_code,405)

    def test_partial_delivery_alone_is_excluded_history_remains(self):
        case=model('ap','Transaction').objects.create(reconciliation_status='partial')
        self.assertEqual(self.get()['count'],2)
        DiscrepancyFinding.objects.filter(ap_transaction=self.cases[0]).update(status='cleared',cleared_at=timezone.now())
        data=self.get({'module':'ap'})
        self.assertEqual(data['count'],1)
        self.assertEqual(data['results'][0]['open_findings_count'],0)

    def test_incomplete_metadata_and_unknown_amount_serialization(self):
        case=model('ap','Transaction').objects.create(reconciliation_status='exception')
        row=next(row for row in self.get()['results'] if row['case_key']==f'ap:{case.pk}')
        self.assertEqual(row['party_name'],'Unknown party')
        self.assertIsNone(row['transaction_date'])
        self.assertEqual(row['currency'],'')
        self.assertIsNone(row['highest_severity'])
        from .presentation import serialize_case_summary
        sample=dict(row,severity_rank=0,discrepancy_amount=None)
        self.assertIsNone(serialize_case_summary(sample)['discrepancy_amount'])
