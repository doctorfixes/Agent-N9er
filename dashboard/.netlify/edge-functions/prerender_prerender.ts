// src/lib/is-crawler.ts
var BOT_DETECTION_PATTERNS = [
  "adsbot-google",
  "ahrefsbot",
  "ahrefssiteaudit",
  "airesearchbot",
  "amazonbot",
  "anthropic-ai",
  "anthropic/claude",
  "apis-google",
  "applebot",
  "baiduspider",
  "baiduspider-ai",
  "baiduspider-render",
  "bingbot",
  "bingbot/ai",
  "bingpreview",
  "bitlybot",
  "bitrix link preview",
  "botifybot",
  "bytedance/tiktok",
  "bytespider",
  "bytespiderbot",
  "ccbot",
  "chatgpt",
  "chatgpt-user",
  "chatgpt-user/1.0",
  "chrome-lighthouse",
  "claude-web",
  "claudebot",
  "cohere",
  "cohere-ai",
  "cohere-crawler",
  "deepcrawl",
  "developers.google.com/+/web/snippet",
  "diffbot",
  "discordbot",
  "dotbot",
  "duckassistbot",
  "duckduckbot",
  "ecosia",
  "embedly",
  "facebookbot",
  "facebookcatalog",
  "facebookexternalhit",
  "facebookexternalhit/ai",
  "feedfetcher-google",
  "flipboard",
  "google - extended",
  "google page speed",
  "google-extended",
  "google-inspectiontool",
  "google-safety",
  "google-site-verification",
  "googlebot",
  "googleother",
  "googleproducer",
  "gptbot",
  "hugging-face-ai",
  "huggingfacebot",
  "iframely",
  "integration-test",
  "linkedinbot",
  "linkedinbot/ai",
  "lumar",
  "mediapartners-google",
  "meta-externalagent",
  "microsoft/bing ai",
  "mistralai-user",
  "naver",
  "neevabot",
  "nuzzel",
  "oai-searchbot",
  "oncrawl bot",
  "oncrawlbot",
  "openai/chatgpt",
  "outbrain",
  "perplexity",
  "perplexity-user",
  "perplexitybot",
  "perplexitybot/1.0",
  "pinterest",
  "pinterest/0.",
  "pinterestbot",
  "quora link preview",
  "qwantbot",
  "qwantify",
  "redditbot",
  "research-crawler",
  "rogerbot",
  "scale-crawler",
  "scaleai",
  "screaming frog",
  "screaming frog seo spider",
  "screaming-frog",
  "semrushbot",
  "seznambot",
  "showyoubot",
  "skypeuripreview",
  "slackbot",
  "sznprohlizec",
  "telegrambot",
  "tiktok",
  "tiktokspider",
  "tumblr",
  "twitter",
  "twitterbot",
  "vkshare",
  "w3c_validator",
  "whatsapp",
  "xing-contenttabreceiver",
  "yabrowser",
  "yahoo",
  "yahoo! slurp",
  "yandex",
  "yandexbot",
  "you-bot",
  "youbot",
  "yourbot"
];
function escapeRegex(str) {
  return str.replace(/[!.*+?^${}()|[\]\\]/g, "\\$&");
}
var CRAWLER_REGEXP = new RegExp(
  BOT_DETECTION_PATTERNS.map((pattern) => escapeRegex(pattern)).join("|"),
  "i"
);
function isCrawler(userAgent) {
  return CRAWLER_REGEXP.test(userAgent);
}

// src/lib/logger.ts
function formatContext(context) {
  return Object.entries(context).map(([key, value]) => `${key}=${value}`).join(" | ");
}
function formatMessage(prefixTag, type, ...args) {
  const formattedArgs = args.map((arg) => {
    if (arg instanceof Error) {
      return arg.message;
    } else if (arg instanceof LoggerDuration) {
      return `${arg.getElapsedTime()}ms`;
    } else if (typeof arg === "object" && arg !== null) {
      return formatContext(arg);
    }
    return String(arg);
  }).join(" | ");
  return `${prefixTag} ${type} ${formattedArgs}`;
}
var PREFIX_TAG = "[PRERENDER]";
var LoggerDuration = class {
  startTime;
  constructor() {
    this.startTime = Date.now();
  }
  getElapsedTime() {
    return Date.now() - this.startTime;
  }
  getFormattedTime() {
    return `${this.getElapsedTime()}ms`;
  }
};
function logger(prefixTag = PREFIX_TAG) {
  return {
    info: (...args) => console.log(formatMessage(prefixTag, "INFO", ...args)),
    warn: (...args) => console.warn(formatMessage(prefixTag, "WARN", ...args)),
    error: (...args) => console.error(formatMessage(prefixTag, "ERROR", ...args))
  };
}

// src/edge-functions/prerender.ts
import crypto from "node:crypto";
var log = logger();
var HEADER_PRERENDER_INT_TYPE = "netlify-extension";
var PRERENDER_TIMEOUT = 1e4;
var CACHE_CONTROL = "public, max-age=3600, s-maxage=86400";
function isValidRequestMethod(method) {
  return ["GET", "HEAD"].includes(method);
}
function getPrerenderConfig() {
  return {
    token: Deno.env.get("PRERENDER_TOKEN_OVERRIDE") || Deno.env.get("PRERENDER_TOKEN") || "",
    enabled: Deno.env.get("PRERENDER_ENABLED") !== "false"
  };
}
function shouldPrerender(config2) {
  const context = { tokenPresent: !!config2.token, enabled: config2.enabled };
  log.info("Configuration state", context);
  if (!config2.token) {
    log.warn("Prerender.io token not configured, serving original content", context);
    return false;
  }
  if (!config2.enabled) {
    log.info("Prerendering disabled, serving original content", context);
    return false;
  }
  return true;
}
function buildPrerenderUrl(url) {
  const serviceUrl = Deno.env.get("PRERENDER_SERVICE_URL") || "https://service.prerender.io";
  const domainOverride = Deno.env.get("PRERENDER_DOMAIN_OVERRIDE");
  if (domainOverride) {
    const overrideUrl = new URL(url.pathname + url.search, domainOverride);
    return `${serviceUrl}/${overrideUrl.href}`;
  }
  return `${serviceUrl}/${url.href}`;
}
function createPrerenderHeaders(request, userAgent, token, requestId) {
  return new Headers({
    ...Object.fromEntries(request.headers.entries()),
    "X-Prerender-Token": token,
    "User-Agent": userAgent,
    "X-Prerender-Int-Type": HEADER_PRERENDER_INT_TYPE,
    "x-prerender-request-id": requestId
  });
}
function enhanceResponseHeaders(headers) {
  const enhancedHeaders = new Headers(headers);
  enhancedHeaders.set("X-Prerendered", "true");
  enhancedHeaders.set("X-Prerendered-By", HEADER_PRERENDER_INT_TYPE);
  if (!enhancedHeaders.has("Cache-Control")) {
    enhancedHeaders.set("Cache-Control", CACHE_CONTROL);
  }
  return enhancedHeaders;
}
async function fetchPrerenderedContent(url, request, headers) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), PRERENDER_TIMEOUT);
  try {
    const response = await fetch(url, {
      method: request.method,
      headers,
      body: request.method !== "GET" && request.method !== "HEAD" ? request.body : void 0,
      signal: controller.signal
    });
    clearTimeout(timeoutId);
    return response;
  } catch (error) {
    clearTimeout(timeoutId);
    throw error;
  }
}
function handlePrerenderError(err, prerenderUrl, duration, requestId) {
  const context = { URL: prerenderUrl, Time: duration.getFormattedTime(), RequestId: requestId };
  if (err instanceof Error && err.name === "AbortError") {
    log.warn(`Timeout after ${PRERENDER_TIMEOUT}ms`, context);
    return;
  }
  const errorMessage = err instanceof Error ? err.message : "Network error";
  log.error(`Fetch failed: ${errorMessage}`, context);
}
var prerender_default = async (request, _context) => {
  const url = new URL(request.url);
  const userAgent = request.headers.get("user-agent") || "";
  log.info("Request", {
    Method: request.method,
    Path: url.pathname + url.search,
    "UA": userAgent || "none"
  });
  if (!isValidRequestMethod(request.method)) {
    log.info("Skipping: Invalid request method", { Method: request.method });
    return;
  }
  if (!isCrawler(userAgent)) {
    log.info("Skipping: Not a crawler request", { "UA": userAgent || "none" });
    return;
  }
  log.info("Crawler detected", { "UA": userAgent });
  const prerenderConfig = getPrerenderConfig();
  if (!shouldPrerender(prerenderConfig)) {
    return;
  }
  const prerenderUrl = buildPrerenderUrl(url);
  const requestId = crypto.randomUUID();
  const prerenderHeaders = createPrerenderHeaders(request, userAgent, prerenderConfig.token, requestId);
  log.info("Fetching", { URL: prerenderUrl });
  const duration = new LoggerDuration();
  try {
    const prerenderResponse = await fetchPrerenderedContent(prerenderUrl, request, prerenderHeaders);
    if (prerenderResponse.ok) {
      log.info("Success", {
        Status: prerenderResponse.status,
        Time: duration.getFormattedTime(),
        RequestId: requestId
      });
      const enhancedHeaders = enhanceResponseHeaders(prerenderResponse.headers);
      return new Response(prerenderResponse.body, {
        status: prerenderResponse.status,
        statusText: prerenderResponse.statusText,
        headers: enhancedHeaders
      });
    }
    log.warn("Non-OK response from Prerender.io", {
      Status: prerenderResponse.status,
      Time: duration.getFormattedTime(),
      URL: prerenderUrl,
      RequestId: requestId
    });
  } catch (error) {
    handlePrerenderError(error, prerenderUrl, duration, requestId);
  }
};
var config = {
  method: "GET",
  // Only paths with no extension, or .html/.htm
  pattern: ["^.*/[^.]*$", "^.*\\.html$", "^.*\\.htm$"],
  excludedPattern: [
    // Exclude development paths of Vite/React
    "^/@.*$",
    // Exclude common framework and API paths
    // eslint-disable-next-line no-useless-escape
    "^/(api|_next|_nuxt|_astro|_serverFn|static|_ipx|\\.netlify)/.*$"
  ]
  // FIXME: Temporarily disabled the edge function level filter, since it's not case insensitive
  // match bot user agents directly on edge function level, won't even fire the function if not a bot
  // header: {
  //   'user-agent': buildCrawlerUserAgentPattern(),
  // }
};
export {
  config,
  prerender_default as default
};
