package tech.enlightenedrepublic.caelza.firstrun

import tech.enlightenedrepublic.caelza.model.ModelLadder

/**
 * The first run's shape, with nothing Android in it so the tests can walk
 * it: the steps in order, the two doors to a brain (design §5, vision §3.4),
 * the `caelza config set` entries each door writes (the same ones
 * `scripts/model-setup.sh` and `caelza quickstart` write on Termux), and
 * Cael's line about what this phone can run. The Activity renders it; the
 * key door's providers and picks come from ModelCatalog (bundle/models.json).
 */
object FirstRun {
    const val PREFS = "caelza"
    const val DONE = "first_run_done"

    enum class Step { HELLO, RUNTIME, BRAIN, SHIZUKU, PERMISSIONS, BATTERY, HUB, START }

    enum class Door { LOCAL, KEY }

    fun next(step: Step): Step? = Step.values().getOrNull(step.ordinal + 1)

    /** Cael on the local guide model with the guide profile: readonly, no tools (`deny_all_tools`, since an empty allow-list means unrestricted). */
    fun caelConfig(provider: String): List<Pair<String, String>> = listOf(
        "agents.cael.model_provider" to provider,
        "agents.cael.risk_profile" to "guide",
        "risk_profiles.guide.level" to "readonly",
        "risk_profiles.guide.deny_all_tools" to "true",
    )

    /** The free, local door: the pick's models behind the llamacpp aliases, the agent on the big one, Cael on the 1.5B. */
    fun localConfig(pick: ModelLadder.Pick): List<Pair<String, String>> = listOf(
        "providers.models.llamacpp.local.model" to pick.agent.name,
        "providers.models.llamacpp.guide.model" to pick.guide.name,
        "agents.main.model_provider" to pick.providerAgent,
    ) + caelConfig(pick.providerGuide)

    /**
     * Bring your own: the key and model under `<provider>.default`, the agent and Cael on it.
     * The provider comes from the curated catalog (ModelCatalog, bundle/models.json); an empty
     * model means its best pick.
     */
    fun keyConfig(provider: ModelCatalog.Provider, model: String, key: String): List<Pair<String, String>> = listOf(
        "providers.models.${provider.id}.default.api_key" to key.trim(),
        "providers.models.${provider.id}.default.model" to model.trim().ifEmpty { provider.best.id },
        "agents.main.model_provider" to provider.alias,
    ) + caelConfig(provider.alias)

    /** A key is one word of some length; the provider says the rest when it is wrong. */
    fun keyLooksRight(key: String): Boolean {
        val k = key.trim()
        return k.length >= 16 && k.none { it.isWhitespace() }
    }

    /** Cael's line about the pick, in his voice. */
    fun pickLine(pick: ModelLadder.Pick): String {
        val gb = "%.1f".format(pick.ramMb / 1024.0)
        val what = if (pick.agent.tier == pick.guide.tier) {
            "one model, ${pick.agent.name} (${pick.agent.mib} MiB), for the agent and for me"
        } else {
            "${pick.agent.name} (${pick.agent.mib} MiB) for the agent and the 1.5B (${pick.guide.mib} MiB) for me"
        }
        val honest = if (pick.agent.tier == GUIDE_TIER_SHORT) {
            "It is good at chat and explanations, less so at long tool-using jobs; for those, bring a key later and keep me local."
        } else {
            "It is tight on a phone, so the agent keeps its context short."
        }
        return "This phone has about $gb GB of RAM, so you'd get $what. $honest"
    }

    private const val GUIDE_TIER_SHORT = ModelLadder.GUIDE_TIER
}
