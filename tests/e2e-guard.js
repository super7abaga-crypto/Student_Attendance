/*
 * Issue #5 — database safety guard for the Django end-to-end run.
 *
 * The E2E script writes attendance rows, so it must never touch a database that
 * holds real data. This module decides, before any database access, whether the
 * resolved database name is clearly disposable.
 *
 * Rules, in order:
 *   1. An empty or unreadable name is ambiguous and is refused.
 *   2. A production-like name (prod, production, live, staging, shared, master,
 *      primary) is refused even with E2E_ALLOW_NON_ISOLATED_DB=1. A typo or a
 *      hurried override must not be able to reach real attendance.
 *   3. A name containing e2e, test or sandbox as a whole segment is allowed.
 *   4. Anything else is refused unless E2E_ALLOW_NON_ISOLATED_DB=1 is set, which
 *      is the documented escape hatch for a freshly created throwaway database
 *      with an unusual name.
 */

const DISPOSABLE_SEGMENT = /(^|[/_.-])(e2e|test|sandbox)([/_.-]|$)/i;
const FORBIDDEN_SEGMENT = /(^|[/_.-])(prod|production|live|staging|shared|master|primary)([/_.-]|$)/i;

function classifyDatabase(dbName, options = {}) {
  const allowNonIsolated = options.allowNonIsolated === true;
  const name = String(dbName == null ? '' : dbName).trim();

  if (!name) {
    return { allowed: false, reason: 'ambiguous',
      message: 'Refusing to run: the database name is empty or could not be resolved.' };
  }
  if (FORBIDDEN_SEGMENT.test(name)) {
    return { allowed: false, reason: 'production-like',
      message: 'Refusing to run: database "' + name + '" looks production-like, shared or staging.\n'
        + 'E2E_ALLOW_NON_ISOLATED_DB cannot override this. Use a database whose name contains e2e, test or sandbox.' };
  }
  if (DISPOSABLE_SEGMENT.test(name)) {
    return { allowed: true, reason: 'disposable', message: 'Disposable database: ' + name };
  }
  if (allowNonIsolated) {
    return { allowed: true, reason: 'override',
      message: 'Proceeding on "' + name + '" because E2E_ALLOW_NON_ISOLATED_DB=1 is set.' };
  }
  return { allowed: false, reason: 'not-designated',
    message: 'Refusing to run: database "' + name + '" does not look disposable.\n'
      + 'Point DATABASE_URL (or the sqlite NAME) at a database whose name contains e2e, test or sandbox,\n'
      + 'or set E2E_ALLOW_NON_ISOLATED_DB=1 after confirming no real attendance lives there.' };
}

function assertDisposableDatabase(dbName, options = {}) {
  const verdict = classifyDatabase(dbName, options);
  if (!verdict.allowed) {
    const error = new Error(verdict.message);
    error.reason = verdict.reason;
    throw error;
  }
  return verdict;
}

module.exports = { classifyDatabase, assertDisposableDatabase, DISPOSABLE_SEGMENT, FORBIDDEN_SEGMENT };
