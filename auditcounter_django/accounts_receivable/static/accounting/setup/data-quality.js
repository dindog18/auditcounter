/* Shared read-only validation report; all source-derived text is escaped. */
(() => {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  function render(report) {
    if (!report) return '';
    return `<section class="finance-callout ${report.blocking_count ? 'warning' : 'info'} mt-3" aria-label="Data quality"><strong>Data quality: ${esc(report.blocking_count)} blocking errors · ${esc(report.warning_count)} warnings</strong><p>Only reviewed mappings are applied. Correct affected fields and run validation again.</p>${report.issues.length ? `<div class="table-responsive"><table class="table"><thead><tr><th>Result</th><th>Field</th><th>Observed value</th><th>Explanation / next action</th></tr></thead><tbody>${report.issues.map(issue => `<tr><td>${esc(issue.blocking ? 'Blocking' : 'Warning')}<br>${esc(issue.code)}</td><td>${esc(issue.field)}</td><td>${esc(issue.observed_value)}</td><td>${esc(issue.explanation)}<br>${esc(issue.suggested_action)}</td></tr>`).join('')}</tbody></table></div>` : '<p class="mb-0">No quality issues detected in the checked records.</p>'}${report.truncated ? '<p>Only the first 200 issues are shown. Correct these and revalidate.</p>' : ''}</section>`;
  }
  window.AccountingDataQuality = {render};
})();
