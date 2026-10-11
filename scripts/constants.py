import re

# Version string is mixed into the graph_builder cache key — increment whenever
# BOT_REGEX changes so stale B_csr pickles are automatically invalidated.
BOT_REGEX_VERSION = "3"

# Registry-operated accounts. npm, Inc. reassigns ownership of a package to the
# 'npm' account when it takes that package down, so in a corpus built from
# caught malware this account accumulates a large share of the corpus purely as
# a consequence of enforcement. Treating it as a maintainer inverts the causal
# arrow — the ownership edge exists BECAUSE the package was caught — and it is
# not an account any attacker can traverse. Excluded for the same reason bots
# are: it is not an attacker-controllable identity.
REGISTRY_ACCOUNTS = ('npm', 'npmjs', 'npm-www', 'npm-cli-ops', 'npmops')

BOT_REGEX = re.compile(
    r'^npm$'               # registry takedown account — see REGISTRY_ACCOUNTS
    r'|^npmjs$'
    r'|^npm-www$'
    r'|^npm-cli-ops$'
    r'|^npmops$'
    r'|.*-bot$'            # suffix: -bot
    r'|.*_bot$'            # suffix: _bot (underscore variant)
    r'|^bot-.*'            # prefix: bot-
    r'|.*-ci$'             # suffix: -ci
    r'|.*\[bot\]$'         # GitHub Actions style: name[bot]
    r'|^npm-support$'
    r'|^greenkeeper$'
    r'|^dependabot$'
    r'|^renovate$'
    r'|^snyk-bot$'
    r'|^semantic-release-bot$'
    r'|^github-actions$'
    r'|^travis-ci$'
    r'|^circleci$'
    r'|.*-service-account$'
    r'|.*-automation$'
    r'|.*-deploy-bot$'
    r'|.*-release-bot$'
)

def is_bot(name):
    if not isinstance(name, str):
        return False
    return bool(BOT_REGEX.match(name))

CUTOFF_DATE = "2026-06-30T23:59:59Z"
