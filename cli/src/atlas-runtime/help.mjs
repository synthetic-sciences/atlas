import { commandGroups, getCommand, listCommands } from "./commands.mjs";
import { optionalFields, requiredFields } from "./parser.mjs";

function fieldMetadata(command, name) {
  const property = command.schema?.properties?.[name] || {};
  const type = property.type || (property.oneOf ? "json" : "string");
  return {
    name,
    type: type === "object" || type === "array" ? "json" : type,
    description: property.description || `${name} parameter.`,
    default: property.default ?? null,
  };
}

function metadata(command) {
  return {
    name: command.name,
    group: command.group,
    summary: command.summary,
    endpoints: command.endpoints,
    required: requiredFields(command).map((name) => fieldMetadata(command, name)),
    optional: optionalFields(command).map((name) => fieldMetadata(command, name)),
    examples: [],
    related: [],
    schema: JSON.stringify(command.schema, null, 2),
  };
}

export function rootHelpJson() {
  return { commands: listCommands().map(metadata) };
}

export function commandHelpJson(name) {
  const command = getCommand(name);
  return command ? metadata(command) : null;
}

export function renderRootHelp() {
  const lines = [
    "Atlas CLI",
    "",
    "Usage:",
    "  atlas <command> [flags]",
    "  atlas help [command] [--format=json] [--schema]",
    "",
    "Command groups:",
  ];
  for (const [group, commands] of commandGroups()) {
    lines.push(`  ${group}`);
    for (const command of commands) {
      const aliases = command.aliases.length ? ` (${command.aliases.join(", ")})` : "";
      lines.push(`    ${command.name}${aliases}  ${command.summary}`);
    }
  }
  lines.push("");
  lines.push("Global options:");
  lines.push("  --format <format>          json | tsv | csv | table | pretty");
  lines.push("  --env <profile>            Use a Atlas CLI profile");
  lines.push("  --out <path>               Write output to a file, or - for stdout");
  lines.push("  --open                     Open browser-bound URLs when supported");
  lines.push("  --no-retry                 Disable transient-error retries");
  lines.push("  --retry-max <n>            Maximum transient-error retry attempts");
  lines.push("  --timeout <seconds>        Per-request HTTP timeout");
  lines.push("  --idempotency-key <key>    Use a caller-supplied key for writes");
  lines.push("  --force                    Force safety-gated operations where supported");
  lines.push("  --yes                      Skip confirmation prompts for destructive operations");
  lines.push("  --debug                    Print structured request debugging");
  return lines.join("\n");
}

export function renderCommandHelp(name) {
  const command = getCommand(name);
  if (!command) return null;
  const required = requiredFields(command);
  const optional = optionalFields(command);
  const lines = [
    `${command.name} - ${command.summary}`,
    "",
    "Usage:",
    `  atlas ${command.name} <FLAGS>`,
    "",
    `Endpoint: ${command.endpoints[0]}`,
  ];
  if (command.aliases.length) lines.push(`Aliases: ${command.aliases.join(", ")}`);
  lines.push("");
  lines.push("Required flags:");
  if (required.length) for (const name of required) lines.push(`  --${name}  ${fieldMetadata(command, name).description}`);
  else lines.push("  None");
  lines.push("");
  lines.push("Optional flags:");
  if (optional.length) for (const name of optional) lines.push(`  --${name}  ${fieldMetadata(command, name).description}`);
  else lines.push("  None");
  return lines.join("\n");
}
