import { execFile } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";

const DEFAULT_BASE_URL = "https://app.syntheticsciences.ai/api/v1";
const KEYCHAIN_SERVICE = "atlas-cli";
const execFileAsync = promisify(execFile);

function nonEmpty(value) {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function defaultConfigPath() {
  return path.join(homedir(), ".config", "atlas-cli", "config.json");
}

export function configPath() {
  return nonEmpty(process.env.ATLAS_CLI_CONFIG_PATH) || defaultConfigPath();
}

export async function readConfig() {
  try {
    return JSON.parse(await readFile(configPath(), "utf8"));
  } catch {
    return {};
  }
}

export async function writeConfig(config) {
  const target = configPath();
  await mkdir(path.dirname(target), { recursive: true, mode: 0o700 });
  await writeFile(target, `${JSON.stringify(config, null, 2)}\n`, { mode: 0o600 });
}

export async function updateProfileConfig(profileName, patch) {
  const config = await readConfig();
  const profile = profileName || config.active_profile || "default";
  const profiles = config.profiles && typeof config.profiles === "object"
    ? { ...config.profiles }
    : {};
  const nextProfile = { ...(profiles[profile] || {}) };
  for (const [key, value] of Object.entries(patch || {})) {
    if (value === undefined) continue;
    if (value === null) delete nextProfile[key];
    else nextProfile[key] = value;
  }
  profiles[profile] = nextProfile;
  const next = { ...config, active_profile: profile, profiles };
  await writeConfig(next);
  return next;
}

export async function clearProfileCredentials(profileName) {
  const config = await readConfig();
  const profile = profileName || config.active_profile || "default";
  const profiles = config.profiles && typeof config.profiles === "object"
    ? { ...config.profiles }
    : {};
  if (profiles[profile]) {
    profiles[profile] = sanitizeProfileCredentials(profiles[profile]);
  }
  const next = { ...config, profiles };
  if (profile === "default") delete next.api_key;
  await writeConfig(next);
  return next;
}

function sanitizeProfileCredentials(profile) {
  const nextProfile = { ...(profile || {}) };
  delete nextProfile.api_key;
  delete nextProfile.api_key_env;
  delete nextProfile.api_key_keychain_service;
  delete nextProfile.api_key_keychain_account;
  delete nextProfile.api_key_source;
  return nextProfile;
}

function redactProfile(name, profile = {}, activeProfile = null) {
  const redacted = { ...profile };
  const inlineKeyPresent = Boolean(nonEmpty(redacted.api_key));
  delete redacted.api_key;
  return {
    name,
    active: activeProfile === name,
    ...redacted,
    api_key_present: Boolean(inlineKeyPresent || nonEmpty(profile.api_key_env) || nonEmpty(profile.api_key_keychain_account)),
    api_key_storage: inlineKeyPresent
      ? "config-redacted"
      : nonEmpty(profile.api_key_env)
        ? "env"
        : nonEmpty(profile.api_key_keychain_account)
          ? "macos-keychain"
          : "none",
  };
}

export async function listProfileConfigs() {
  const config = await readConfig();
  const profiles = config.profiles && typeof config.profiles === "object" ? config.profiles : {};
  const names = [...new Set(["default", ...Object.keys(profiles)])].sort();
  return {
    config_path: configPath(),
    active_profile: config.active_profile || "default",
    profiles: names.map((name) => redactProfile(name, profiles[name] || {}, config.active_profile || "default")),
  };
}

export async function showProfileConfig(profileName) {
  const config = await readConfig();
  const profile = profileName || config.active_profile || "default";
  const profiles = config.profiles && typeof config.profiles === "object" ? config.profiles : {};
  return {
    config_path: configPath(),
    active_profile: config.active_profile || "default",
    profile: redactProfile(profile, profiles[profile] || {}, config.active_profile || "default"),
  };
}

export async function setProfileConfig(profileName, patch, { makeActive = true } = {}) {
  const config = await readConfig();
  const profile = profileName || config.active_profile || "default";
  const profiles = config.profiles && typeof config.profiles === "object" ? { ...config.profiles } : {};
  const nextProfile = { ...(profiles[profile] || {}) };
  for (const [key, value] of Object.entries(patch || {})) {
    if (value === undefined) continue;
    if (value === null) delete nextProfile[key];
    else nextProfile[key] = value;
  }
  if (nextProfile.api_key_env) {
    delete nextProfile.api_key;
    delete nextProfile.api_key_keychain_service;
    delete nextProfile.api_key_keychain_account;
    delete nextProfile.api_key_source;
  }
  profiles[profile] = nextProfile;
  const next = {
    ...config,
    profiles,
    active_profile: makeActive ? profile : (config.active_profile || "default"),
  };
  await writeConfig(next);
  return await showProfileConfig(profile);
}

export async function unsetProfileConfig(profileName) {
  const config = await readConfig();
  const profile = profileName || config.active_profile || "default";
  const profiles = config.profiles && typeof config.profiles === "object" ? { ...config.profiles } : {};
  delete profiles[profile];
  const names = Object.keys(profiles).sort();
  const next = { ...config, profiles };
  if ((config.active_profile || "default") === profile) {
    if (names.length) next.active_profile = names[0];
    else delete next.active_profile;
  }
  await writeConfig(next);
  return {
    config_path: configPath(),
    unset: true,
    profile,
    active_profile: next.active_profile || "default",
  };
}

async function readKeychainApiKey(profileEntry, profile) {
  const account = nonEmpty(profileEntry.api_key_keychain_account);
  const service = nonEmpty(profileEntry.api_key_keychain_service);
  if (!account || !service || process.platform !== "darwin") return null;
  try {
    const { stdout } = await execFileAsync("security", [
      "find-generic-password",
      "-a",
      account,
      "-s",
      service,
      "-w",
    ]);
    return nonEmpty(stdout);
  } catch {
    return null;
  }
}

function requireMacKeychain() {
  if (process.platform !== "darwin") {
    throw new Error("secret:set and secret:clear are only supported on macOS. Use config:set --api-key-env <ENV_NAME> and provide that environment variable instead.");
  }
}

export async function setProfileKeychainCredential(profileName, apiKey) {
  requireMacKeychain();
  const profile = profileName || "default";
  const key = nonEmpty(apiKey);
  if (!key) throw new Error("secret:set expects an API key on stdin");
  await execFileAsync("security", [
    "add-generic-password",
    "-a",
    profile,
    "-s",
    KEYCHAIN_SERVICE,
    "-w",
    key,
    "-U",
  ]);
  await updateProfileConfig(profile, {
    api_key: null,
    api_key_env: null,
    api_key_keychain_service: KEYCHAIN_SERVICE,
    api_key_keychain_account: profile,
    api_key_source: "macos-keychain",
  });
  return {
    profile,
    keychain: { service: KEYCHAIN_SERVICE, account: profile, stored: true },
  };
}

export async function clearProfileKeychainCredential(profileName) {
  requireMacKeychain();
  const profile = profileName || "default";
  try {
    await execFileAsync("security", [
      "delete-generic-password",
      "-a",
      profile,
      "-s",
      KEYCHAIN_SERVICE,
    ]);
  } catch {
    // Deleting a missing key is still a successful clear from the CLI user's perspective.
  }
  await updateProfileConfig(profile, {
    api_key_keychain_service: null,
    api_key_keychain_account: null,
    api_key_source: null,
  });
  return {
    profile,
    keychain: { service: KEYCHAIN_SERVICE, account: profile, cleared: true },
  };
}

function profileConfig(config, profileName) {
  const profiles = config.profiles && typeof config.profiles === "object"
    ? config.profiles
    : {};
  return profiles[profileName] || {};
}

export async function resolveRuntimeConfig(overrides = {}) {
  const config = await readConfig();
  const profile =
    nonEmpty(overrides.env) ||
    nonEmpty(process.env.ATLAS_PROFILE) ||
    nonEmpty(config.active_profile) ||
    "default";
  const profileEntry = profileConfig(config, profile);
  const apiKeyEnv = nonEmpty(profileEntry.api_key_env);
  const apiKey =
    nonEmpty(overrides.apiKey) ||
    nonEmpty(process.env.ATLAS_API_KEY) ||
    (apiKeyEnv ? nonEmpty(process.env[apiKeyEnv]) : null) ||
    await readKeychainApiKey(profileEntry, profile) ||
    nonEmpty(profileEntry.api_key) ||
    nonEmpty(config.api_key);
  const baseUrl =
    nonEmpty(overrides.baseUrl) ||
    nonEmpty(process.env.ATLAS_BASE_URL) ||
    nonEmpty(profileEntry.base_url) ||
    nonEmpty(config.base_url) ||
    DEFAULT_BASE_URL;

  return {
    profile,
    baseUrl: baseUrl.replace(/\/+$/, ""),
    apiKey,
    timeoutMs: Number(overrides.timeoutMs || process.env.ATLAS_TIMEOUT_MS || profileEntry.timeout_ms || 300_000),
    retryMax: Number(overrides.retryMax ?? profileEntry.retry_max ?? 2),
    defaultFormat: nonEmpty(profileEntry.default_format) || "json",
  };
}
