Release Notes | SpaceXAI Docs Docs Search ⌘ K API Console Products Grok Status Loading...
Resources llms.txt Discord Email support Terms and Policies Get Started Welcome Grok 4.6 Latest Quickstart Models New Pricing Release Notes Grok Build Getting Started Modes and Commands Keyboard Shortcuts Features Settings CLI Enterprise Deployments Text Text Generation Reasoning Structured Outputs Streaming Multi Agent Completions (Legacy) Imagine Overview Image Generation Image Editing Multi-Image Editing Video Generation Image-to-Video Reference-to-Video New Video Editing Video Extension Files API Integration Voice New Overview Ephemeral Tokens Speech to Speech Text to Speech Speech to Text
Custom Voices New Resources Rate Limits Cost Tracking Debugging Errors Docs MCP Files & Collections Files Overview Managing Files Public URLs New Chat with Files Collections Collections via API Collection Metadata Tools Overview Function Calling Web Search X Search Code Execution Image Generation Collections Search (RAG) Remote MCP Tools Deep Dive Advanced API Usage Batch API Deferred Completions Prompt Caching Context Compaction New Priority Processing New mTLS Authentication Async Requests WebSocket Mode New Migration Guides Imagine Image Quality Retirement on Nov 2 New Model Retirement on
May 15 Migrating to Responses API Community Community Integrations Google Cloud Vertex AI Microsoft Foundry FAQ Data & Privacy General Docs Grok Bot Grok & Console REST API gRPC Get Started Welcome Grok 4.6 Latest Quickstart Models New Pricing Release Notes Grok Build Getting Started Modes and Commands Keyboard Shortcuts Features Settings CLI Enterprise Deployments Text Text Generation Reasoning Structured Outputs Streaming Multi Agent Completions (Legacy) Imagine Overview Image Generation Image Editing Multi-Image Editing Video Generation Image-to-Video Reference-to-Video New Video Editing
Video Extension Files API Integration Voice New Overview Ephemeral Tokens Speech to Speech Text to Speech Speech to Text Custom Voices New Resources Rate Limits Cost Tracking Debugging Errors Docs MCP Files & Collections Files Overview Managing Files Public URLs New Chat with Files Collections Collections via API Collection Metadata Tools Overview Function Calling Web Search X Search Code Execution Image Generation Collections Search (RAG) Remote MCP Tools Deep Dive Advanced API Usage Batch API Deferred Completions Prompt Caching Context Compaction New Priority Processing New mTLS
Authentication Async Requests WebSocket Mode New Migration Guides Imagine Image Quality Retirement on Nov 2 New Model Retirement on May 15 Migrating to Responses API Community Community Integrations Google Cloud Vertex AI Microsoft Foundry FAQ Data & Privacy General Release Notes Release Notes Copy for LLM View as Markdown Create API key Meet grok-4.6 September September 2 grok-imagine-image-quality retirement on November 2 On November 2, 2026, grok-imagine-image-quality is retired.
Requests to the slug will be served by grok-imagine-image-2.0 with quality set to low , with no change to the request or response shape and at a lower per-image price.
grok-imagine-image (1.0) is not affected.
See the migration guide .
August August 28 Imagine image API updates Auto quality.
The quality parameter on grok-imagine-image-2.0 now accepts auto , and the default when quality is omitted has moved from medium to auto .
Auto currently uses low for image generation and medium for image editing.
Images are billed at the quality they are served at.
Pass low or medium explicitly to pin a specific quality.
See Image Generation .
Five reference images.
Image editing now accepts up to 5 source images per request (was 3).
See Multi-Image Editing .
New aspect ratios.
Image generation and editing accept 21:9 (cinematic widescreen) and 5:2 (wide banners).
See Image Generation .
August 12 Grok 4.6 Grok 4.6, SpaceXAI's frontier model for coding, agentic tasks, and knowledge work, is now available on the xAI API.
It has a 500k context window, text and image inputs with text-only output, and no text output limit.
Pricing is $2 / $0.50 / $6 per 1M tokens (input / cached input / output) below 200k prompt tokens, and $4 / $1 / $12 above.
Reasoning effort supports low, medium, high (default), and xhigh.
See the Grok 4.6 overview and the announcement .
August 11 Grok Bot Grok Bot is now available.
Durable AI teammates that work on a persistent cloud computer, with messaging, approvals, connectors, and routines.
See the Grok Bot overview and Get started .
July July 31 grok-imagine-video-1.5 modalities grok-imagine-video-1.5 now supports text-to-video, image-to-video, and reference-to-video (including optional preset voices), with native 1080p for T2V and I2V.
Text-to-video on this model runs as text-to-image then image-to-video under the hood.
See Video Generation , Image-to-Video , and Reference-to-Video .
July 29 Grok Voice Think Fast 2.0 is available grok-voice-think-fast-2.0 is now available with Speech to Speech.
grok-voice-latest will route to this model starting August 5, 2026.
To get started, see the Speech to Speech docs .
For more details, see our announcement .
July 23 Adjustable VAD threshold for Speech to Text Speech to Text now accepts a vad_threshold parameter (streaming query param and batch multipart field) to tune the voice-activity gate that skips non-speech audio.
Lower values transcribe quieter or noisier speech — useful for narrowband telephony — and 0 disables the gate.
See the Speech to Text docs .
July 17 Grok 4.5 available in the EU Grok 4.5 is now available in the API console for EU users.
See the Grok 4.5 overview .
July 8 Grok 4.5 Grok 4.5, SpaceXAI's model for coding, agentic tasks, and knowledge work, is now available on the xAI API.
Priced at $2 / 1M input tokens and $6 / 1M output tokens, with configurable reasoning effort (low, medium, or high; default high).
See the Grok 4.5 overview and the announcement .
June June 15 Priority Processing You can now request higher scheduling priority per request by setting service_tier: "priority" on text inference endpoints (Chat Completions and Responses).
The response's service_tier field reports the tier actually applied, and priority rates are billed only when priority is used.
For more details, see the Priority Processing docs .
June 10 Public URLs and Files API ↔ Imagine integration Public URLs for Files — turn any file in your Files API storage into a permanent, unauthenticated URL that anyone can open, embed, or share.
Revocable at any time, or set an auto-expiry between 1 hour and 30 days.
See the Public URLs docs .
Reference stored files as Imagine inputs — substitute image_file_id , video_file_id , or reference_image_file_ids for URL inputs across every Imagine endpoint, with no need to re-upload bytes or make the file public.
See Imagine → Files API Integration .
Persist Imagine outputs to Files — set storage_options on any Imagine request to save the generated asset to your Files storage; pair with storage_options.public_url to publish a shareable link in one round trip.
See Imagine → Files API Integration .
May May 29 Smart Turn for Streaming STT The streaming Speech to Text API now supports Smart Turn end-of-turn detection.
When enabled via the smart_turn query parameter, an ML model predicts whether the speaker has finished their thought at silence boundaries — reducing false endpointing during dictation, number sequences, and mid-sentence pauses.
Use smart_turn_timeout to set a maximum silence fallback.
For more details, see the Smart Turn docs .
May 29 Context Compaction The Context Compaction API is now available.
You can shrink long conversations into a shorter context and reuse it in follow-up requests for lower cost, faster time-to-first-token, and sharper responses on long agent loops.
For more details, see the Context Compaction docs .
WebSocket Responses API Mode WebSocket Responses API mode is now available.
Drive the Responses API over a single, long-lived WebSocket connection for lower end-to-end latency on tool-heavy agent workloads.
For more details, see the WebSocket Mode docs .
May 27 Image Search in Web Search Web Search now supports explicitly searching for images.
Enable enable_image_search to let Grok search directly for relevant images; responses can include returned images as Markdown image embeds.
For details, see Enable Image Search .
May 19 Grok Build 0.1 xAI's coding model, trained specifically for agentic coding workflows.
Currently in early access.
The model slug is grok-build-0.1 .
May 14 Grok Build Grok Build is now available in beta.
Use the interactive TUI, run headlessly in scripts, or build apps and orchestrators with the Agent Client Protocol.
Install with a single command: Bash curl -fsSL https://x.ai/cli/install.sh | bash For more details, see the Grok Build docs .
May 1 Custom Voices You can now clone a voice from a short audio clip and use it across the Text-to-Speech and Speech to Speech APIs.
Create and manage your voice catalog from the xAI console.
For more details, check out the Custom Voices docs and our blog post .
April Apr 30 Cost Tracking Every API response now includes the exact cost of the request via a cost_in_usd_ticks field in the usage object.
Works across chat completions, Responses API, image generation, video generation, and streaming.
For more details, see the Cost Tracking docs .
Apr 28 Files API TTL You can now set an expiration policy on uploaded files using expires_after or an explicit expires_at timestamp.
Expired files are automatically deleted.
For more details, see the Files API docs .
Apr 23 Grok Voice Think Fast 1.0 is available You can now use grok-voice-think-fast-1.0 with the Speech to Speech API.
To get started, check out the Speech to Speech docs .
For more details, see our blog post .
Apr 15 Speech to Text is available The xAI Speech to Text API is now generally available.
Transcribe audio to text in 25 languages with batch and streaming modes.
For more details, check out the Speech to Text docs .
March Mar 16 Text-to-Speech is available The Text-to-Speech API is now generally available.
Generate natural-sounding speech from text with Grok.
For more details, check out the Text-to-Speech docs .
Mar 15 Batch API supports Image and Video generation The Batch API now supports image generation , image editing , and video generation in addition to chat completions.
Both server-side tools and client-side function tools are also now supported in batch requests.
Image and video URLs in batch results expire after 1 hour.
Batch API JSONL file upload You can now create batches by uploading a JSONL file via the Files API.
Supports all batch endpoints including chat, image, and video in a single file.
Mar 10 Grok 4.20 and Grok 4.20 Multi-agent are live For more details on Grok 4.20 Multi-agent, check out the docs January Jan 28 Video Generation & Next-Gen Image Generation Video Generation and a revamped Image Generation are now available.
Batch API is released Batch API is available for all customers.
It enables efficient batch processing of multiple requests, providing a better experience for users who need to submit large volumes of requests at once.
December 2025 Dec 16 Grok Speech to Speech API is released Grok Speech to Speech API is generally available.
Visit Grok Speech to Speech API for guidance on using the API.
November 2025 Nov 19 Grok 4.1 Fast is available in Enterprise API You can now use Grok 4.1 Fast in the xAI Enterprise API .
For more details, check out our blogpost .
Agent tools adapt to Grok 4.1 Fast models and tool prices dropped You can now use Grok 4.1 Fast models with the agent tools, check out the documentation of agent tools to get started.
The price of agent tools drops by up to 50% to no more than $5 per 1000 successful calls, see the new prices at the pricing page .
Nov 7 Files API is generally available You can now upload files and use them in chat conversations with the Files API.
For more details, check out our guide on Files .
New Tools Available Collections Search Tool : You can now search through uploaded knowledge bases (collections) in chat conversations via the API.
For more details, check out the docs .
Remote MCP Tools : You can now use tools from remote MCP servers in chat conversations via the API.
For more details, check out the docs .
Mixing client-side and server-side tools : You can now mix client-side and server-side tools in the same chat conversation.
For more details, check out the docs .
October 2025 Oct 15 Tools are now generally available New agentic server-side tools including web_search , x_search , and code_execution are available.
For more details, check out our guide on using Tools .
September 2025 Sep 15 Responses API is generally available You can now use our stateful Responses API to process requests.
August 2025 Aug 15 Collections API is released You can upload files, create embeddings, and use them for inference with our Collections API.
July 2025 Jul 9 Grok 4 is released You can now use Grok 4 via our API or on https://grok.com .
June 2025 Jun 6 Management API is released You can manage your API keys via Management API at https://management-api.x.ai .
May 2025 May 29 Cached prompt is now available You can now use cached prompt to save on repeated prompts.
For more info, see models .
May 20 Live Search is available on API Live search is now available on API.
Users can generate completions with queries on supported data sources.
April 2025 Apr 3 Grok 3 models launch on API Our latest flagship Grok 3 models are now generally available via the API.
For more info, see models .
March 2025 Mar 19 Image Generation Model available on API The image generation model is available on API.
Visit Image Generations for more details on using the model.
February 2025 Feb 7 Audit Logs Team admins can now view audit logs on console.x.ai .
January 2025 Jan 24 Docs Dark Mode Released dark mode support on docs.x.ai Jan 6 Status Page Check service statuses across all SpaceXAI products at status.x.ai .
December 2024 Dec 31 Replit & xAI Replit Agents can now integrate with xAI!
Start empowering your agents with Grok.
Check out the announcement for more information.
Dec 30 Tokenizer Playground Understanding tokens can be hard.
Check out console.x.ai to get a better understanding of what counts as a token.
Dec 17 Structured Outputs We're excited to announce that Grok now supports structured outputs.
Grok can now format responses in a predefined, organized format rather than free-form text.
1.
Specify the desired schema Text { "name": "movie_response", "schema": { "type": "object", "properties": { "title": { "type": "string" }, "rating": { "type": "number" } }, "required": [ "title", "rating" ], "additionalProperties": false }, "strict": true } Get the desired data Text { "title": "Star Wars", "rating": 8.6 } Start building more reliable applications.
Check out the docs for more information.
Dec 14 Released the new grok-2-1212 and grok-2-vision-1212 models A month ago, we launched the public beta of our enterprise API with grok-beta and grok-vision-beta.
We’re adding grok-2-1212 and grok-2-vision-1212 , offering better accuracy, instruction-following, and multilingual capabilities.
November 2024 Nov 19 LangChain & xAI Our API is now available through LangChain!
Python Docs: https://python.langchain.com/integrations/providers/xai/ Javascript Docs: https://js.langchain.com/integrations/chat/xai/ What are you going to build?
Nov 4 API Public Beta We are happy to announce the immediate availability of our API, which gives developers programmatic access to our Grok series of foundation models.
To get started, head to console.x.ai and sign up to create an account.
We are excited to see what developers build using Grok.
Last updated: September 2, 2026
