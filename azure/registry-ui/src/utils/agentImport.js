function slugifyCapabilityName(text, index) {
  const slug = String(text || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return (slug || `capability_${index + 1}`).slice(0, 64);
}

function normalizeEndpoint(rawEndpoint) {
  const endpoint = String(rawEndpoint || "").trim().replace(/\/+$/, "");
  if (!endpoint) return endpoint;

  let normalized = endpoint;
  const legacyPath = normalized.match(/^(.+?)\/([^/]+)\/api$/i);
  if (legacyPath) {
    normalized = `${legacyPath[1]}/api/${legacyPath[2]}`;
  }

  // In local Docker setups orchestrator runs in a container and should reach
  // host services through host.docker.internal.
  normalized = normalized
    .replace("://localhost:", "://host.docker.internal:")
    .replace("://127.0.0.1:", "://host.docker.internal:");

  return normalized;
}

function responsePathForAgent(agentName) {
  const map = {
    billing_agent: "answer",
    customer_lookup_agent: "output",
    conversation_summary_agent: "output",
    anomaly_detection_agent: "",
  };
  return map[agentName] || "";
}

function bodyTemplateForAgent(agent) {
  const props = agent?.input_schema?.properties || {};
  const template = {};
  if (Object.prototype.hasOwnProperty.call(props, "query")) {
    template.query = "{task}";
  } else {
    template.task = "{task}";
  }
  if (Object.prototype.hasOwnProperty.call(props, "customer_id")) {
    template.customer_id = "{customer_id}";
  }
  if (Object.prototype.hasOwnProperty.call(props, "context")) {
    template.context = "{context}";
  }
  return template;
}

export function parseImportJson(rawText) {
  let parsed;
  try {
    parsed = JSON.parse(rawText);
  } catch (err) {
    throw new Error(`Invalid JSON: ${err.message}`);
  }

  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("JSON root must be an object.");
  }
  if (!Array.isArray(parsed.agents)) {
    throw new Error("JSON must include an 'agents' array.");
  }
  return parsed;
}

export function toRegistryAgentPayload(coreAgent) {
  const name = String(coreAgent?.name || "").trim();
  const description = String(coreAgent?.description || "").trim();
  const endpoint = coreAgent?.endpoint || coreAgent?.endpoint_url || "";
  const endpointUrl = normalizeEndpoint(endpoint);

  if (!name) throw new Error("Agent is missing required field: name");
  if (!description) throw new Error(`Agent '${name}' is missing required field: description`);
  if (!endpointUrl) throw new Error(`Agent '${name}' is missing required field: endpoint`);
  if (!/^https?:\/\//i.test(endpointUrl)) {
    throw new Error(`Agent '${name}' endpoint must start with http:// or https://`);
  }

  const capabilities = Array.isArray(coreAgent.capabilities)
    ? coreAgent.capabilities
        .map((cap, index) => {
          const desc = String(cap || "").trim();
          if (!desc) return null;
          return {
            name: slugifyCapabilityName(desc, index),
            description: desc,
            input_schema: {},
            output_schema: {},
          };
        })
        .filter(Boolean)
    : [];

  return {
    name,
    description,
    endpoint_url: endpointUrl,
    version: String(coreAgent.version || "1.0.0"),
    utility_types: Array.isArray(coreAgent.utility_types) ? coreAgent.utility_types : ["multi"],
    tags: Array.isArray(coreAgent.tags) ? coreAgent.tags : ["core-json", "imported"],
    capabilities,
    auth_config: coreAgent.auth_config || { auth_type: "none" },
    health_check_config: coreAgent.health_check_config || { check_type: "http" },
    invocation_config:
      coreAgent.invocation_config || {
        http_method: "POST",
        content_type: "application/json",
        body_template: bodyTemplateForAgent(coreAgent),
        response_result_path: responsePathForAgent(name),
      },
    metadata: {
      ...(coreAgent.metadata || {}),
      source: "registry-ui-import",
      source_schema: "src/core/agents.schema.json",
      legacy_timeout_seconds: coreAgent.timeout_seconds ?? null,
    },
  };
}

export function buildImportPayloads(parsedJson) {
  const errors = [];
  const payloads = [];

  parsedJson.agents.forEach((agent, idx) => {
    try {
      payloads.push(toRegistryAgentPayload(agent));
    } catch (err) {
      errors.push(`Item ${idx + 1}: ${err.message}`);
    }
  });

  return { payloads, errors };
}
