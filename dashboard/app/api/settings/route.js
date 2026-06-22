import { promises as fs } from "fs";
import path from "path";

const SETTINGS_PATH = process.env.SETTINGS_PATH || path.join(process.cwd(), ".agent-settings.json");

const DEFAULTS = {
  agent: {
    alias: "Agent N9er",
    description: "Autonomous freelance work agent",
    avatar_emoji: "9",
  },
  api: {
    openrouter_model: "anthropic/claude-sonnet-4-20250514",
    openrouter_fallback: "anthropic/claude-haiku-4-5-20251001",
    default_timeout: 10,
    max_retries: 3,
  },
  scanning: {
    auto_scan_enabled: false,
    scan_interval_seconds: 3600,
    scan_platforms: "upwork,github_bounties,freelancer,web_search,reddit,hackernews",
    scan_keywords: "freelance developer needed,looking for developer,need a programmer,hire a developer,software project,build me,API integration,bot development",
    reddit_subreddits: "forhire,slavelabour,freelance_forhire,WorkOnline",
    craigslist_regions: "newyork,sfbay,losangeles",
    custom_rss_feeds: "",
    auto_evaluate: false,
  },
  guardrails: {
    max_single_task_usd: 500,
    max_daily_spend_usd: 2000,
    require_approval_above_usd: 100,
    auto_execute_enabled: true,
  },
  billing: {
    markup_multiplier: 3.0,
    minimum_quote_usd: 5.0,
  },
  notifications: {
    smtp_host: "",
    smtp_port: 587,
    smtp_user: "",
    notify_email: "",
    notify_min_budget: 100,
  },
};

async function loadSettings() {
  try {
    const raw = await fs.readFile(SETTINGS_PATH, "utf-8");
    const saved = JSON.parse(raw);
    const merged = {};
    for (const [section, defaults] of Object.entries(DEFAULTS)) {
      merged[section] = { ...defaults, ...(saved[section] || {}) };
    }
    return merged;
  } catch {
    return { ...DEFAULTS };
  }
}

async function saveSettings(settings) {
  await fs.writeFile(SETTINGS_PATH, JSON.stringify(settings, null, 2), "utf-8");
}

export async function GET() {
  const settings = await loadSettings();
  return Response.json(settings);
}

export async function PUT(request) {
  const body = await request.json();
  const current = await loadSettings();

  for (const [section, values] of Object.entries(body)) {
    if (current[section]) {
      for (const [key, val] of Object.entries(values)) {
        if (key in current[section]) {
          current[section][key] = val;
        }
      }
    }
  }

  await saveSettings(current);
  return Response.json({ ok: 1, settings: current });
}
