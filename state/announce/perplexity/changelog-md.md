> ## Documentation Index > Fetch the complete documentation index at: https://docs.perplexity.ai/llms.txt > Use this file to discover all available pages before exploring further.
# Changelog <Tip> Looking ahead?
Check out our [Feature Roadmap](/docs/resources/feature-roadmap) to see what's coming next.
</Tip> <Update label="August 2026" tags={["Agent API", "Router", "Models"]}> **GLM 5.3** The Agent API and Router API now support `perplexity/glm-5.3` at \$1.40 per million uncached-input tokens, \$0.26 per million cached-input tokens, and \$4.40 per million output tokens.
See the [Agent API Models reference](/docs/agent-api/models) or the [Router model catalog](/docs/router/models).
</Update> <Update label="August 2026" tags={["Agent API", "Presets"]}> **Prompt caching for presets** Agent API presets now use stable prompt cache keys automatically, allowing independent requests with the same preset to reuse the shared prompt prefix (system prompt and tool definitions).
No request changes are required, and an explicit `prompt_cache_key` still overrides the preset default.
This can reduce costs by about 5% for applications that use presets frequently, depending on cache utilization.
The [current preset values](/docs/agent-api/presets#current-preset-values) include each key for frozen configurations.
</Update> <Update label="August 2026" tags={["Agent API", "Presets"]}> **Fast preset updated** The Agent API `fast` preset now uses `openai/gpt-5.6-luna` with `minimal` reasoning effort and priority processing.
Dynamic `fast` preset requests pick up the change automatically.
If you use a [frozen configuration](/docs/agent-api/presets#current-preset-values), update the model and reasoning effort and set `service_tier` to `priority`.
Priority processing uses 2× the model's standard token prices.
</Update> <Update label="August 2026" tags={["Agent API", "Router", "Models"]}> **Gemini 3.7 Flash** The Agent API and Router API now support `google/gemini-3.7-flash` at launch pricing of \$0.375 per million input tokens, \$0.0375 per million cached-input tokens, and \$1.875 per million output tokens.
See the [Agent API Models reference](/docs/agent-api/models).
</Update> <Update label="August 2026" tags={["Agent API", "Models"]}> **Grok 4.6** The Agent API now supports `xai/grok-4.6`, xAI's latest flagship reasoning and agentic model.
See pricing in the [Agent API Models reference](/docs/agent-api/models).
</Update> <Update label="August 2026" tags={["Agent API", "Models"]}> **NVIDIA Nemotron 3 Ultra** The Agent API and Router API now support `perplexity/nemotron-3-ultra-550b-a55b` at \$0.25 per million input or cached-input tokens and \$2.50 per million output tokens.
See the [Agent API Models reference](/docs/agent-api/models) or the [Router model catalog](/docs/router/models).
</Update> <Update label="August 2026" tags={["Agent API", "Router", "Models"]}> **NVIDIA Nemotron 3.5 Lightning** The Agent API and Router API now support `perplexity/nemotron-3.5-lightning-30b-a3b`, a fast, efficient open-weight reasoning model, at \$0.0115 per million input tokens, \$0.00115 per million cached-input tokens, and \$0.17 per million output tokens.
See the [Agent API Models reference](/docs/agent-api/models) or the [Router model catalog](/docs/router/models).
</Update> <Update label="August 2026" tags={["Agent API", "Router", "Models"]}> **DeepSeek V4 Flash 0731** The Agent API and Router API now support `perplexity/deepseek-v4-flash-0731`, a fast, efficient open reasoning model with a 1M-token context window.
See pricing in the [Agent API Models reference](/docs/agent-api/models) or the [Router model catalog](/docs/router/models).
</Update> <Update label="July 2026" tags={["Agent API", "Models", "Pricing"]}> **GPT-5.6 price cuts and Sol Fast mode** GPT-5.6 Luna now costs \$0.20 per million input tokens and \$1.20 per million output tokens.
GPT-5.6 Terra now costs \$2 per million input tokens and \$12 per million output tokens.
GPT-5.6 Sol now supports Fast mode at 2× standard token pricing; send `service_tier: "priority"` to use it.
</Update> <Update label="July 2026" tags={["Router", "Features"]}> **New: Router API** Unified access to open-weight models hosted by Perplexity through a single endpoint — with your existing Perplexity API key.
**Key features:** * OpenAI Chat Completions and Anthropic Messages compatibility: switching is a base-URL change * Automatic health-based routing and failover across model deployments * Per-token pricing at each model's published rates, with no per-request fees [Get started with the Router API →](/docs/router/quickstart) </Update> <Update label="July 2026" tags={["MCP"]}> **Remote MCP Server** The [Perplexity MCP Server](/docs/getting-started/integrations/mcp-server) is now available as a remote server hosted by Perplexity at `https://api.perplexity.ai/mcp`.
Connect any MCP client that supports Streamable HTTP using your API key as a bearer token, with no local installation and nothing to update.
Tools and behavior are identical to the local server, and usage is billed to your API key at standard API pricing.
</Update> <Update label="July 2026" tags={["Agent API", "Presets"]}> **Low preset updated** The Agent API `low` preset now uses `openai/gpt-5.6-luna` with `minimal` reasoning effort and a 32,768-token maximum output.
If you use a [frozen configuration](/docs/agent-api/presets#current-preset-values), update these values to match the current preset.
Dynamic `low` preset requests pick up the change automatically.
</Update> <Update label="July 2026" tags={["Agent API", "Presets"]}> **Inline citations for research presets** The Agent API's search-backed presets include inline citations: `fast` cites claims drawn from search results with numbered citations such as `[1]`, while `low`, `medium`, and `high` now cite claims drawn from tool results or provided source artifacts with source-typed citations such as `[web:1]`.
After a successful tool call, the `low`, `medium`, and `high` presets include at least one citation in the final answer.
The [current preset values](/docs/agent-api/presets#current-preset-values) include the system prompts for frozen configurations.
</Update> <Update label="July 2026" tags={["MCP", "Agent API"]}> **MCP Server 1.0: now backed by the Agent API** The [Perplexity MCP Server](/docs/getting-started/integrations/mcp-server) v1.0.0 moves its model-backed tools from the legacy Sonar models to [Agent API presets](/docs/agent-api/presets): `perplexity_ask` uses the `fast` preset, `perplexity_reason` uses `medium`, and `perplexity_research` uses `high`.
Tool names and response shapes are unchanged, and all three tools are faster and cheaper on average than their Sonar predecessors.
Long-running research now streams progress to MCP clients that request it, and cancelling an MCP request cancels the underlying run.
The `strip_thinking` and `reasoning_effort` parameters were removed from the tool schemas (the Agent API emits no think tags, and presets manage reasoning effort); clients still sending them are ignored gracefully.
</Update> <Update label="July 2026" tags={["Agent API", "Deprecation"]}> **Sonar Chat Completions migration** More models, tools, and research-backed presets: Sonar Chat Completions is now [Agent API.](/docs/agent-api/quickstart) Migration guide [here](/docs/agent-api/migrate-from-sonar/overview).
</Update> <Update label="July 2026" tags={["Agent API", "Models"]}> **Agent API: New Models** The Agent API added support for several new models this month, all with direct first-party token pricing.
See the full list in the [Agent API Models reference](/docs/agent-api/models).
**Claude Opus 5** The Agent API now supports `anthropic/claude-opus-5`.
**GPT-5.6 Family** The Agent API now supports `openai/gpt-5.6-sol`, `openai/gpt-5.6-terra`, and `openai/gpt-5.6-luna`, giving you access to the latest GPT-5.6 models.
**Gemini Flash Models** The Agent API now supports `google/gemini-3.6-flash` and `google/gemini-3.5-flash-lite`, adding Google's latest fast and cost-efficient models.
**Grok 4.5** The Agent API now supports `xai/grok-4.5`, xAI's flagship coding and agentic model.
**Kimi K3** The Agent API now supports `perplexity/kimi-k3`, Moonshot AI's flagship reasoning model.
See the [Agent API Models reference](/docs/agent-api/models) for pricing and model-specific settings.
**Retired: Gemini 3.1 Flash Lite Preview** `google/gemini-3.1-flash-lite-preview` has been retired: Google removed the underlying preview model from its API.
Requests for this id now return a `model not supported` error.
Use `google/gemini-3.1-flash-lite` instead — the stable successor at the same pricing.
See the [Agent API Models reference](/docs/agent-api/models).
</Update> <Update label="June 2026" tags={["Agent API", "Models"]}> **Agent API: New Models** The Agent API expanded model coverage this month, all with direct first-party token pricing.
See the full list in the [Agent API Models reference](/docs/agent-api/models).
* **Claude Sonnet 5** — `anthropic/claude-sonnet-5`, Anthropic's latest Sonnet model.
* **GLM 5.2** — `perplexity/glm-5.2`, Z.AI's flagship reasoning model.
* **Kimi K2.7 Code** — `perplexity/kimi-k2.7-code`, Moonshot AI's coding and agentic model.
* **Nemotron 3 Super** — `nvidia/nemotron-3-super-120b-a12b`, NVIDIA's open-weight reasoning model.
</Update> <Update label="May 2026" tags={["Agent API", "Models"]}> **Agent API: New Models** The Agent API added support for several new third-party models this month, all with direct first-party token pricing.
See the full list in the [Agent API Models reference](/docs/agent-api/models).
* **Claude Opus 4.8** — `anthropic/claude-opus-4-8`, Anthropic's flagship model.
* **Gemini 3.5 Flash** — `google/gemini-3.5-flash`, Google's fast multimodal model.
* **Gemini 3.1 Flash Lite** — `google/gemini-3.1-flash-lite` (and `-preview`), a cost-efficient option.
* **Grok 4.3** and the **Grok 4.20** family — `xai/grok-4.3`, `xai/grok-4.20-non-reasoning`, and `xai/grok-4.20-multi-agent`.
</Update> <Update label="May 2026" tags={["Agent API", "Tools", "Finance"]}> **Finance Search: Now Available** The `finance_search` tool is now available in the Agent API.
Pull structured financial and market data — quotes, financials, earnings, analyst estimates, segment KPIs, ETF constituents, and more — for public companies and instruments.
The model decides which fields to fetch based on your prompt, so a single call can return valuation, earnings, and context together.
**Highlights:** * **Quotes and pricing**: Near-real-time prices, OHLCV ranges, pre-market and after-hours data * **Financials**: Income statement, balance sheet, cash flow (quarterly and annual), key ratios * **Earnings**: Last call transcript, filings, beat/miss history, guidance * **Coverage and market activity**: Analyst estimates, top gainers/losers, ownership and corporate actions * **Recommended configurations**: Presets for live quotes, single-company historical lookups, and multi-step cross-company research Start here: [Finance Search](/docs/agent-api/tools/finance-search) </Update>
<Update label="April 2026" tags={["Integrations", "AWS", "Models", "Billing", "Security"]}> **Agent API: New Third-Party Models** The Agent API now supports Claude Opus 4.7, GPT-5.5, and Grok 4.20 Reasoning — extending model choice for tool-calling, structured outputs, and fallback chains.
See the full list in the [Agent API Models reference](/docs/agent-api/models).
**API Key Management: Security Upgrade** We've upgraded API key management with a one-time reveal model: full token values are now returned **only at the moment of creation** and cannot be retrieved again from the console or any endpoint.
This significantly reduces the blast radius of credential exposure and aligns with industry best practices.
Always set a descriptive `token_name` so keys remain identifiable after creation, and rotate regularly.
Start here: [API Key Management](/docs/admin/api-key-management) **New Integration: n8n** n8n now ships a native Perplexity node with full API coverage — Chat Completions, Agent, Search, and Embeddings — all configurable from the visual canvas.
Models load dynamically from the API, so the dropdown always reflects the latest options.
Start here: [n8n Integration Guide](/docs/getting-started/integrations/n8n) **New Integration: OpenClaw** OpenClaw, the open-source terminal AI agent, now supports Perplexity Search API as a native web search provider.
Configure your API key once and get structured search results (`title`, `url`, `snippet`) directly inside your terminal workflows.
Start here: [OpenClaw Integration Guide](/docs/getting-started/integrations/openclaw) **API Credits now available through the AWS Marketplace** The Perplexity API Platform is now available as a SaaS listing on AWS Marketplace.
Purchase API credits through your AWS account for consolidated billing, simplified procurement, and no separate vendor relationship.
Start here: [AWS Marketplace](/docs/resources/aws-marketplace) **`/v1/models` Endpoint** A new `GET /v1/models` endpoint lists all available Agent API models in OpenAI-compatible format.
No authentication required, useful for dynamic model selection in your integrations.
</Update> <Update label="March 2026" tags={["Agent API", "Models", "Deprecation", "SDK"]}> **Agent API: New Third-Party Models** The Agent API now supports additional third-party models including GPT-5.4, NVIDIA Nemotron, Claude Sonnet 4.6, and Gemini 3.1 Pro Preview — giving you more flexibility for tool-calling, structured outputs, and model fallback chains.
**Model Deprecations: Gemini 2.5 Flash & Gemini 2.5 Pro** As of March 20, 2026, `google/gemini-2.5-flash` has been deprecated and removed from the API.
`google/gemini-2.5-pro` followed on April 1, along with `google/gemini-3-pro-preview`.
If you were using these models, we recommend switching to newer alternatives available in the [Agent API Models reference](/docs/agent-api/models).
**Agent API Endpoint: `/v1/agent`** The canonical Agent API endpoint is now `/v1/agent`.
The previous `/v1/responses` path continues to work as an alias for OpenAI compatibility, no migration is required.
</Update> <Update label="February 2026" tags={["Agent API", "Embeddings", "Docs"]}> **Agent API: Now Available** We're excited to announce the general availability of the **Agent API**!
Build autonomous agents with production-ready guidance on model behavior, output controls, and OpenAI-compatibility patterns to seamlessly integrate with your existing systems.
Start here: [Agent API Quickstart](/docs/agent-api/quickstart) **Embeddings API: Now Available** We're thrilled to launch the **Embeddings API** with comprehensive guides for standard and contextualized embeddings, plus best practices for semantic search and retrieval workflows.
Start here: [Embeddings API Quickstart](/docs/embeddings/quickstart) </Update> <Update label="December 2025" tags={["Models", "Deprecation", "Search"]}> **Model Deprecation: `sonar-reasoning` Removed** As of December 15, 2025, the `sonar-reasoning` model has been deprecated and removed from the API.
If you were using this model, we recommend migrating to `sonar-reasoning-pro` for enhanced multi-step reasoning capabilities with web search.
**New: Media Classifier for Intelligent Visual Content** We're excited to introduce the **Media Classifier** — an intelligent system that automatically detects when your queries would benefit from visual content and includes relevant images or videos in responses.
**Key capabilities:** * **Automatic detection**: Analyzes queries to identify when visual content adds value * **Smart media selection**: Intelligently chooses between images, videos, or both based on query type * **Context-aware**: Perfect for educational content, geographic queries, processes, and demonstrations * **Configurable control**: Enable/disable and override media types as needed Available exclusively with `sonar-pro`, the Media Classifier enhances responses for visual concepts, locations, step-by-step processes, and educational content.
[Learn more →](/docs/sonar/media) **Search API Enhancements** We've made several improvements to the Search API: * **New `max_tokens` parameter**: Control the maximum tokens extracted per page in search results.
This gives you finer control over response size and costs.
[Learn more →](/docs/search/quickstart) * **`last_updated_filter` support**: Filter search results by when content was last updated, in addition to publication date.
Perfect for finding the most current information.
[Learn more →](/docs/search/filters/date-time-filters) * **Vercel AI SDK Support**: The Search API is now compatible with the Vercel AI SDK, allowing you to build with Perplexity in a framework-agnostic way.
[Learn more →](https://ai-sdk.dev/tools-registry/perplexity-search) **Ecosystem & Community** New community showcase: [**Perplexity Client**](/docs/cookbook/showcase/perplexity-client) — An Electron-based desktop application with advanced API parameter controls, custom spaces, and API debugging mode.
Built by the community for developers who want fine-grained control over their Sonar interactions.
</Update> <Update label="November 2025" tags={["Pro Search", "MCP", "Multimodal"]}> **Pro Search: Now Generally Available** We're excited to announce the general availability of **Pro Search** for Sonar Pro!
Pro Search enhances your queries with automated tool usage, enabling multi-step reasoning through intelligent tool orchestration.
**Key capabilities:** * **Multi-step reasoning**: The model automatically performs multiple web searches and fetches URL content to answer complex queries * **Real-time thought streaming**: Watch the model's reasoning process as it works through your question * **Automatic classification**: Use `search_type: "auto"` to let the system intelligently route queries based on complexity * **Built-in tools**: Access `web_search` and `fetch_url_content` tools that the model uses automatically Learn more about Pro Search in our [Pro Search Quickstart](/docs/sonar/pro-search/quickstart) guide.
**MCP Server: One-Click Installation** The [Perplexity MCP Server](/docs/getting-started/integrations/mcp-server) now supports **one-click installation** for popular AI development environments: * **Cursor**: Click to auto-configure the Perplexity MCP server * **VS Code**: One-click setup via the VS Code MCP extension * **Claude Desktop & Claude Code**: Easy JSON configuration The MCP server provides four powerful tools: `perplexity_search`, `perplexity_ask`, `perplexity_research`, and `perplexity_reason` — enabling AI assistants to access Perplexity's search and reasoning capabilities
directly.
</Update> <Update label="October 2025" tags={["SDK", "Playground", "Search", "Features"]}> **Official Perplexity SDKs** We're thrilled to announce the official **Perplexity SDKs** for Python and Typescript!
These SDKs provide convenient, type-safe access to all Perplexity APIs with both synchronous and asynchronous clients.
**Installation:** ```bash theme={null} # Python pip install perplexityai # Typescript npm install @perplexity-ai/perplexity_ai ``` **Features:** * Full type definitions for all request parameters and response fields * Support for Sonar and Search APIs * Streaming support with async iterators * Automatic environment variable handling for API keys Get started with our [SDK Quickstart Guide](/docs/sdk/overview) and explore the [Sonar API Guide](/docs/sonar/quickstart) for detailed usage examples.
**Interactive Search API Playground** Test Search API queries and parameters in real time with our new [Interactive Playground](https://console.perplexity.ai) — **no API key required** to get started.
Experiment with filtering options, see response structures, and refine your queries before implementing them in code.
**New Search API Capabilities** * **`language_preference`**: Specify preferred languages for search results (available for `sonar` and `sonar-pro`) * **`search_domain_filter`**: Filter results to specific domains for more targeted searches * **Date/time filters**: Enhanced control over result freshness with publication and update filters **Ecosystem & Community** New community showcase: [**StarPlex**](/docs/cookbook/showcase/starplex) — An AI-powered startup intelligence platform featuring an interactive 3D globe interface.
Built with Sonar Pro, it helps entrepreneurs validate business ideas by mapping competitors, VCs, and market opportunities worldwide.
Featured at recent hackathon events!
</Update> <Update label="September 2025" tags={["File Attachments", "Multimodal"]}> **New: File Attachments Support** You can now upload and analyze documents in multiple formats using Sonar models!
This powerful new feature supports PDF, DOC, DOCX, TXT, and RTF files, allowing you to ask questions, extract information, and get summaries from your documents.
**Key capabilities:** * **Document Analysis**: Ask questions about document content and get detailed answers * **Content Extraction**: Pull out key information, data points, and insights * **Multi-format Support**: Work with PDF, Word documents, text files, and Rich Text Format * **Large Document Handling**: Process lengthy documents efficiently * **Multi-language Support**: Analyze documents in various languages Upload documents either via publicly accessible URLs using the `file_url` content type, similar to our existing image upload functionality.
Get started with our comprehensive [File Attachments Guide](/docs/sonar/media#sending-files).
</Update> <Update label="September 2025" tags={["Search", "Features"]}> **New: Search-only API** Introducing our standalone Search API that provides direct access to search results without LLM processing!
This new endpoint gives you raw, ranked search results from Perplexity's continuously refreshed index.
**Perfect for:** * Building custom search experiences * Integrating search results into your own applications * Creating specialized workflows that need search data without AI responses * Applications requiring just the search functionality **Key features:** * Direct access to Perplexity's search index * All existing search filters and controls * Faster responses since no LLM processing is involved * Same powerful filtering options (domain, date range, academic sources, etc.) This complements our existing chat completions API and gives developers more flexibility in how they use Perplexity's
search capabilities.
Learn more in our [Search API documentation](/docs/search/quickstart).
</Update> <Update label="September 2025" tags={["Security", "API Keys"]}> **New: API Key Rotation Mechanism** We've introduced a comprehensive API key rotation system to enhance security and simplify key management for your applications.
**Key features:** * **Seamless Rotation**: Replace API keys without service interruption * **Automated Workflows**: Set up automatic key rotation schedules * **Enhanced Security**: Regularly refresh keys to minimize security risks * **Audit Trail**: Track key usage and rotation history * **Zero Downtime**: Smooth transitions between old and new keys **How it works:** 1.
Generate a new API key while keeping the old one active 2.
Update your applications to use the new key 3.
Deactivate the old key once migration is complete This is particularly valuable for production environments where continuous availability is critical, and for organizations with strict security compliance requirements.
**Best practices:** * Rotate keys every 30-90 days depending on your security requirements * Use environment variables to manage keys in your applications * Test key rotation in staging environments first * Monitor key usage to ensure successful transitions Access key rotation features through your [API Portal](https://console.perplexity.ai).
</Update> <Update label="August 2025" tags={["Models", "Deprecation"]}> **API model deprecation notice** Please note that as of August 1, 2025, R1-1776 will be removed from the available models.
R1 has been a popular option for a while, but it hasn't kept pace with recent improvements and lacks support for newer features.
To reduce engineering overhead and make room for more capable models, we're retiring it from the API.
If you liked R1's strengths, we recommend switching to `Sonar Pro Reasoning`.
It offers similar behavior with stronger overall performance.
</Update> <Update label="July 2025" tags={["Cost Tracking", "Usage"]}> **New: Detailed Cost Information in API Responses** The API response JSON now includes detailed cost information for each request.
You'll now see a new structure like this in your response: ```json theme={null} "usage": { "prompt_tokens": 8, "completion_tokens": 439, "total_tokens": 447, "search_context_size": "low", "cost": { "input_tokens_cost": 2.4e-05, "output_tokens_cost": 0.006585, "request_cost": 0.006, "total_cost": 0.012609 } } ``` **What's included:** * **input\_tokens\_cost**: Cost attributed to input tokens * **output\_tokens\_cost**: Cost attributed to output tokens * **request\_cost**: Fixed cost per request * **total\_cost**: The total cost for this API call This update enables easier tracking of usage and
billing directly from each API response, giving you complete transparency into the costs associated with each request.
</Update> <Update label="July 2025" tags={["Search", "Financial"]}> **New: SEC Filings Filter for Financial Research** We're excited to announce the release of our new SEC filings filter feature, allowing you to search specifically within SEC regulatory documents and filings.
By setting `search_domain: "sec"` in your API requests, you can now focus your searches on official SEC documents, including 10-K reports, 10-Q quarterly reports, 8-K current reports, and other regulatory filings.
This feature is particularly valuable for: * Financial analysts researching company fundamentals * Investment professionals conducting due diligence * Compliance officers tracking regulatory changes * Anyone requiring authoritative financial information directly from official sources The SEC filter works seamlessly with other search parameters like date filters and search context size, giving you precise control over your financial research queries.
**Example:** ```bash theme={null} curl --request POST \ --url https://api.perplexity.ai/v1/sonar \ --header 'accept: application/json' \ --header 'authorization: Bearer $PERPLEXITY_API_KEY' \ --header 'content-type: application/json' \ --data '{ "model": "sonar-pro", "messages": [{"role": "user", "content": "What was Apple's revenue growth in their latest quarterly report?"}], "stream": false, "search_domain": "sec", "web_search_options": {"search_context_size": "medium"} }' | jq ``` For detailed documentation and implementation examples, please see our [SEC
Guide](https://docs.perplexity.ai/guides/sec-guide).
</Update> <Update label="June 2025" tags={["Search", "Filters"]}> **Enhanced: Date Range Filtering with Latest Updated Field** We've enhanced our date range filtering capabilities with new fields that give you even more control over search results based on content freshness and updates.
**New fields available:** * `latest_updated`: Filter results based on when the webpage was last modified or updated * `published_after`: Filter by original publication date (existing) * `published_before`: Filter by original publication date (existing) The `latest_updated` field is particularly useful for: * Finding the most current version of frequently updated content * Ensuring you're working with the latest data from news sites, blogs, and documentation * Tracking changes and updates to specific web resources over time **Example:** ```bash theme={null} curl --request POST \ --url
https://api.perplexity.ai/v1/sonar \ --header 'accept: application/json' \ --header 'authorization: Bearer $PERPLEXITY_API_KEY' \ --header 'content-type: application/json' \ --data '{ "model": "sonar-pro", "messages": [{"role": "user", "content": "What are the latest developments in AI research?"}], "stream": false, "web_search_options": { "latest_updated": "2025-06-01", "search_context_size": "medium" } }' ``` For comprehensive documentation and more examples, please see our [Date Range Filter Guide](https://docs.perplexity.ai/guides/date-range-filter-guide).
</Update> <Update label="June 2025" tags={["Search", "Filters", "Academic"]}> **New: Academic Filter for Scholarly Research** We're excited to announce the release of our new academic filter feature, allowing you to tailor your searches specifically to academic and scholarly sources.
By setting `search_mode: "academic"` in your API requests, you can now prioritize results from peer-reviewed papers, journal articles, and research publications.
This feature is particularly valuable for: * Students and researchers working on academic papers * Professionals requiring scientifically accurate information * Anyone seeking research-based answers instead of general web content The academic filter works seamlessly with other search parameters like `search_context_size` and date filters, giving you precise control over your research queries.
**Example:** ```bash theme={null} curl --request POST \ --url https://api.perplexity.ai/v1/sonar \ --header 'accept: application/json' \ --header 'authorization: Bearer $PERPLEXITY_API_KEY' \ --header 'content-type: application/json' \ --data '{ "model": "sonar-pro", "messages": [{"role": "user", "content": "What is the scientific name of the lions mane mushroom?"}], "stream": false, "search_mode": "academic", "web_search_options": {"search_context_size": "low"} }' ``` For detailed documentation and implementation examples, please see our [Academic Filter
Guide](https://docs.perplexity.ai/guides/academic-filter-guide).
</Update> <Update label="May 2025" tags={["Models", "Reasoning"]}> **New: Reasoning Effort Parameter for Sonar Deep Research** We're excited to announce our new reasoning effort feature for sonar-deep-research.
This lets you control how much computational effort the AI dedicates to each query.
You can choose from "low", "medium", or "high" to get faster, simpler answers or deeper, more thorough responses.
This feature has a direct impact on the amount of reasoning tokens consumed for each query, giving you the ability to control costs while balancing between speed and thoroughness.
**Options:** * `"low"`: Faster, simpler answers with reduced token usage * `"medium"`: Balanced approach (default) * `"high"`: Deeper, more thorough responses with increased token usage **Example:** ```bash theme={null} curl --request POST \ --url https://api.perplexity.ai/v1/sonar \ --header 'accept: application/json' \ --header 'authorization: Bearer ${PPLX_KEY}' \ --header 'content-type: application/json' \ --data '{ "model": "sonar-deep-research", "messages": [{"role": "user", "content": "What should I know before markets open today?"}], "stream": true, "reasoning_effort": "low" }' ``` For
detailed documentation and implementation examples, please see: [Sonar Deep Research Documentation](/docs/sonar/models/sonar-deep-research) </Update> <Update label="May 2025" tags={["Models", "Async"]}> **New: Asynchronous API for Sonar Deep Research** We're excited to announce the addition of an asynchronous API for Sonar Deep Research, designed specifically for research-intensive tasks that may take longer to process.
This new API allows you to submit requests and retrieve results later, making it ideal for complex research queries that require extensive processing time.
The asynchronous API endpoints include: 1.
`GET https://api.perplexity.ai/v1/async/sonar` - Lists all asynchronous chat completion requests for the authenticated user 2.
`POST https://api.perplexity.ai/v1/async/sonar` - Creates an asynchronous chat completion job 3.
`GET https://api.perplexity.ai/v1/async/sonar/{request_id}` - Retrieves the status and result of a specific asynchronous chat completion job **Note:** Async requests have a time-to-live (TTL) of 7 days.
After this period, the request and its results will no longer be accessible.
For detailed documentation and implementation examples, please see: [Sonar Deep Research Documentation](/docs/sonar/models/sonar-deep-research) </Update> <Update label="May 2025" tags={["Search", "Breaking Change"]}> **Enhanced API Responses with Search Results** We've improved our API responses to give you more visibility into search data by adding a new `search_results` field to the JSON response object.
This enhancement provides direct access to the search results used by our models, giving you more transparency and control over the information being used to generate responses.
The `search_results` field includes: * `title`: The title of the search result page * `url`: The URL of the search result * `date`: The publication date of the content **Example:** ```json theme={null} "search_results": [ { "title": "Understanding Large Language Models", "url": "https://example.com/llm-article", "date": "2023-12-25" }, { "title": "Advances in AI Research", "url": "https://example.com/ai-research", "date": "2024-03-15" } ] ``` This update makes it easier to: * Verify the sources used in generating responses * Create custom citation formats for your applications * Filter or
prioritize certain sources based on your needs **Update: The `citations` field has been fully deprecated and removed.** All applications should now use the `search_results` field, which provides more detailed information including titles, URLs, and publication dates.
The `search_results` field is available across all our search-enabled models and offers enhanced source tracking capabilities.
</Update> <Update label="April 2025" tags={["Organization", "Portal"]}> **New API Portal for Organization Management** We are excited to announce the release of our new API portal, designed to help you better manage your organization and API usage.
With this portal, you can: * Organize and manage your API keys more effectively.
* Gain insights into your API usage and team activity.
* Streamline collaboration within your organization.
Check it out here:\ [https://console.perplexity.ai](https://console.perplexity.ai) </Update> <Update label="April 2025" tags={["Search", "Filters"]}> **New: Location filtering in search** Looking to narrow down your search results based on users' locations?\ We now support user location filtering, allowing you to retrieve results only from a particular user location.
Check out the [guide](https://docs.perplexity.ai/guides/user-location-filter-guide).
</Update> <Update label="April 2025" tags={["Images", "Multimodal"]}> **Image uploads now available for all users!** You can now upload images to Sonar and use them as part of your multimodal search experience.\ Give it a try by following our image upload guide:\ [https://docs.perplexity.ai/guides/image-attachments](https://docs.perplexity.ai/guides/image-attachments) </Update> <Update label="April 2025" tags={["Search", "Filters"]}> **New: Date range filtering in search** Looking to narrow down your search results to specific dates?\ We now support date range filtering, allowing you to
retrieve results only from a particular timeframe.
Check out the guide:\ [https://docs.perplexity.ai/guides/date-range-filter-guide](https://docs.perplexity.ai/guides/date-range-filter-guide) </Update> <Update label="April 2025" tags={["Pricing"]}> **Clarified: Search context pricing update** We've fully transitioned to our new pricing model: citation tokens are no longer charged.\ If you were already using the `search_context_size` parameter, you've been on this model already.
This change makes pricing simpler and cheaper for everyone — with no downside.
View the updated pricing:\ [https://docs.perplexity.ai/guides/pricing](https://docs.perplexity.ai/guides/pricing) </Update> <Update label="April 2025" tags={["Features", "Access"]}> **All features now available to everyone** We've removed all feature gating based on tiered spending.
These were previously only available to users of Tier 3 and above.
That means **every user now has access to all API capabilities**, regardless of usage volume or spend.
Rate limits are still applicable.\ Whether you're just getting started or scaling up, you get the full power of Sonar out of the box.
</Update> <Update label="March 2025" tags={["Structured Outputs", "Features"]}> **Structured Outputs Available for All Users** We're excited to announce that structured outputs are now available to all Perplexity API users, regardless of tier level.
Based on valuable feedback from our developer community, we've removed the previous Tier 3 requirement for this feature.
**What's available now:** * JSON structured outputs are supported across all models This change allows developers to create more reliable and consistent applications from day one.
We believe in empowering our community with the tools they need to succeed, and we're committed to continuing to improve accessibility to our advanced features.
Thank you for your feedback—it helps us make Perplexity API better for everyone.
</Update> <Update label="March 2025" tags={["Models", "Search", "Pricing"]}> **Improved Sonar Models: New Search Modes** We're excited to announce significant improvements to our Sonar models that deliver superior performance at lower costs.
Our latest benchmark testing confirms that Sonar and Sonar Pro now outperform leading competitors while maintaining more affordable pricing.
Key updates include: * **Three new search modes** across most Sonar models: * High: Maximum depth for complex queries * Medium: Balanced approach for moderate complexity * Low: Cost-efficient for straightforward queries (equivalent to current pricing) * **Simplified billing structure**: * Transparent pricing for input/output tokens * No charges for citation tokens in responses (except for Sonar Deep Research) The current billing structure will be supported as the default option for 30 days (until April 18, 2025).
During this period, the new search modes will be available as opt-in features.
**Important Note:** After April 18, 2025, Sonar Pro and Sonar Reasoning Pro will not return Citation tokens or number of search results in the usage field in the API response.
</Update> <Update label="January 2025" tags={["Models", "Deprecation"]}> **API model deprecation notice** Please note that as of February 22, 2025, several models and model name aliases will no longer be accessible.
The following model names will no longer be available via API: `llama-3.1-sonar-small-128k-online` `llama-3.1-sonar-large-128k-online` `llama-3.1-sonar-huge-128k-online` We recommend updating your applications to use our recently released Sonar or Sonar Pro models – you can learn more about them here.
Thank you for being a Perplexity API user.
</Update> <Update label="January 2025" tags={["Models", "Features"]}> **Build with Perplexity's new APIs** We are expanding API offerings with the most efficient and cost-effective search solutions available: **Sonar** and **Sonar Pro**.
**Sonar** gives you fast, straightforward answers **Sonar Pro** tackles complex questions that need deeper research and provides more sources Both models offer built-in citations, automated scaling of rate limits, and public access to advanced features like structured outputs and search domain filters.
And don't worry, we never train on your data.
Your information stays yours.
You can learn more about our new APIs here - [https://docs.perplexity.ai](https://docs.perplexity.ai) </Update> <Update label="November 2024" tags={["Citations", "Rate Limits"]}> **Citations Public Release and Increased Default Rate Limits** We are excited to announce the public availability of citations in the Perplexity API.
In addition, we have also increased our default rate limit for the sonar online models to 50 requests/min for all users.
Effective immediately, all API users will see citations returned as part of their requests by default.
This is not a breaking change.
The **return\_citations** parameter will no longer have any effect.
For bug reports or enterprise inquiries, please reach out to our team at [api@perplexity.ai](mailto:api@perplexity.ai) </Update> <Update label="July 2024" tags={["Models", "Deprecation"]}> **Introducing New and Improved Sonar Models** We are excited to announce the launch of our latest Perplexity Sonar models: **Online Models** - `llama-3.1-sonar-small-128k-online` `llama-3.1-sonar-large-128k-online` **Chat Models** - `llama-3.1-sonar-small-128k-chat` `llama-3.1-sonar-large-128k-chat` These new additions surpass the performance of the previous iteration.
For detailed information on our supported models, please visit our model card documentation.
**\[Action Required]** Model Deprecation Notice Please note that several models will no longer be accessible effective 8/12/2024.
We recommend updating your applications to use models in the Llama-3.1 family immediately.
The following model names will no longer be available via API - `llama-3-sonar-small-32k-online` `llama-3-sonar-large-32k-online` `llama-3-sonar-small-32k-chat` `llama-3-sonar-large-32k-chat` `llama-3-8b-instruct` `llama-3-70b-instruct` `mistral-7b-instruct` `mixtral-8x7b-instruct` We recommend switching to models in the Llama-3.1 family: **Online Models** - `llama-3.1-sonar-small-128k-online` `llama-3.1-sonar-large-128k-online` **Chat Models** - `llama-3.1-sonar-small-128k-chat` `llama-3.1-sonar-large-128k-chat` **Instruct Models** - `llama-3.1-70b-instruct` `llama-3.1-8b-instruct` If you
have any questions, please email [support@perplexity.ai](mailto:support@perplexity.ai).
Thank you for being a Perplexity API user.
Stay curious, Team Perplexity </Update> *** <Update label="April 2024" tags={["Models", "Deprecation"]}> **Model Deprecation Notice** Please note that as of May 14, several models and model name aliases will no longer be accessible.
We recommend updating your applications to use models in the Llama-3 family immediately.
The following model names will no longer be available via API: `codellama-70b-instruct` `mistral-7b-instruct` `mixtral-8x22b-instruct` `pplx-7b-chat` `pplx-7b-online` </Update>
