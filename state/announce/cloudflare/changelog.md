Changelog · Cloudflare Workers AI docs Skip to content Documentation Index Fetch the complete documentation index at: https://developers.cloudflare.com/workers-ai/llms.txt Use this file to discover all available pages before exploring further.
Docs Directory API SDKs Changelog Search Ctrl K Log in Dashboard Workers AI / Overview Getting started Overview Workers Bindings REST API Dashboard Models Configuration Workers Bindings OpenAI compatible API endpoints Vercel AI SDK Hugging Face Chat UI Features Asynchronous Batch API Beta Overview Workers Binding REST API Function calling Beta Overview Embedded Beta Overview Get Started Examples Use fetch() handler Tools based on OpenAPI Spec Use KV API API Reference Troubleshooting Traditional Beta JSON Mode Fine-tunes Overview Using LoRA adapters Beta Public LoRA adapters Prompt caching
Prompting Markdown Conversion Beta Overview Usage Workers Binding REST API Supported Formats How it works Conversion Options Guides Demos and architectures Tutorials Agents ↗ Platform Pricing Data usage Limits Glossary AI Gateway ↗ Errors Choose a data or storage product ↗ Event subscriptions Agents ↗ Playground Changelog REST API reference ↗ API Agent resources Agent setup ↗ Cloudflare Skills ↗ Code Mode MCP Server ↗ Domain-specific MCP Servers ↗ MCP Workers AI llms.txt ↗ Workers AI llms-full.txt ↗ Cloudflare Docs llms.txt ↗ Cloudflare Docs llms-full.txt ↗ Home / Workers AI / Changelog
Changelog Last updated Apr 21, 2026 | Copy as Markdown | View as Markdown | Agent setup Subscribe to RSS 2026-06-16 GLM-5.2 now available on Workers AI @cf/zai-org/glm-5.2 is now available on Workers AI.
Z.ai's flagship agentic coding model with a 262,144 token context window, function calling, and reasoning support.
Read changelog to get started.
2026-06-12 Moonshot AI Kimi K2.7 Code now available on Workers AI @cf/moonshotai/kimi-k2.7-code now available on Workers AI.
A frontier-scale 1T parameter MoE model optimized for coding, with a 262.1k context window, vision, multi-turn tool calling, and reasoning.
Read changelog to get started.
2026-05-08 Planned model deprecations We are refreshing the Workers AI model catalog to make room for newer releases.
Please update your apps to remove references to the models listed below before the deprecation date.
Refer to the changelog for full details.
We recommend migrating to newer models such as @cf/zai-org/glm-4.7-flash for fast tool-calling, @cf/google/gemma-4-26b-a4b-it for an efficient open model, or @cf/moonshotai/kimi-k2.6 for a capable tool-calling and vision model.
On May 30, 2026, requests to @cf/moonshotai/kimi-k2.5 will be automatically aliased to @cf/moonshotai/kimi-k2.6 , which has a higher price.
The deprecation date was extended from May 10, 2026.
Please review the K2.6 pricing and model capabilities prior to May 30, 2026.
On May 30, 2026, the following models will be deprecated: @cf/moonshotai/kimi-k2.5 --> @cf/moonshotai/kimi-k2.6 @hf/meta-llama/meta-llama-3-8b-instruct @cf/meta/llama-3-8b-instruct @cf/meta/llama-3-8b-instruct-awq @cf/meta/llama-3.1-8b-instruct @cf/meta/llama-3.1-8b-instruct-awq @cf/meta/llama-3.1-70b-instruct @cf/meta/llama-2-7b-chat-int8 @cf/meta/llama-2-7b-chat-fp16 @cf/mistral/mistral-7b-instruct-v0.1 @hf/mistral/mistral-7b-instruct-v0.2 @hf/google/gemma-7b-it @cf/google/gemma-3-12b-it @hf/nousresearch/hermes-2-pro-mistral-7b @cf/microsoft/phi-2 @cf/defog/sqlcoder-7b-2
@cf/unum/uform-gen2-qwen-500m @cf/facebook/bart-large-cnn The -fast and -lora variants of models will remain active.
LoRA models may be deprecated in the future, and we will communicate when new LoRA models come online to give users time to train new LoRAs before we deprecate old ones.
2026-04-20 Moonshot AI Kimi K2.6 now available on Workers AI @cf/moonshotai/kimi-k2.6 now available on Workers AI.
The latest frontier-scale model from Moonshot AI with improved reasoning, coding, and agentic capabilities.
Read changelog to get started.
K2.6 uses the chat_template_kwargs.thinking parameter to control reasoning (instead of chat_template_kwargs.enable_thinking ) and returns reasoning content in the reasoning field (instead of reasoning_content ).
2026-04-04 Google Gemma 4 26B A4B now available on Workers AI @cf/google/gemma-4-26b-a4b-it now available on Workers AI.
A Mixture-of-Experts model with 26B total parameters and 4B active, featuring a 256K context window, vision, built-in thinking mode, and function calling.
Read changelog to get started.
2026-03-19 Moonshot AI Kimi K2.5 now available on Workers AI @cf/moonshotai/kimi-k2.5 now available on Workers AI.
A frontier-scale open-source model with a 256k context window, multi-turn tool calling, vision inputs, and structured outputs for agentic workloads.
Read changelog to get started.
New Prompt caching documentation.
Send the x-session-affinity header to route requests to the same model instance and maximize prefix cache hit rates across multi-turn conversations.
Redesigned Asynchronous Batch API with a pull-based system that processes queued requests as capacity becomes available, avoiding out-of-capacity errors for durable workflows.
2026-03-11 NVIDIA Nemotron 3 Super now available on Workers AI @cf/nvidia/nemotron-3-120b-a12b now available on Workers AI!
A hybrid MoE model with 120B total parameters and 12B active, optimized for multi-agent and agentic AI workloads.
Read changelog to get started.
2026-03-06 Deepgram Nova-3 now supports 10 languages with regional variants @cf/deepgram/nova-3 now supports 10 languages with regional variants for real-time transcription.
Supported languages include English, Spanish, French, German, Hindi, Russian, Portuguese, Japanese, Italian, and Dutch — with regional variants like en-GB , fr-CA , and pt-BR .
2026-02-17 Chat Completions API support for gpt-oss models and tool calling improvements @cf/openai/gpt-oss-120b and @cf/openai/gpt-oss-20b now support Chat Completions API format.
Use /v1/chat/completions with a messages array, or use /ai/run which dynamically detects your input format and accepts Chat Completions ( messages ), legacy Completions ( prompt ), or Responses API ( input ).
[Bug fix] Fixed a bug in the schema for multiple text generation models where the content field in message objects only accepted string values.
The field now properly accepts both string content and array content (structured content parts for multi-modal inputs).
This fix applies to all affected chat models including GPT-OSS models, Llama 3.x, Mistral, Qwen, and others.
[Bug fix] Tool call round-trips now work correctly.
The binding no longer rejects tool_call_id values that it generated itself, fixing issues with multi-turn tool calling conversations.
[Bug fix] Assistant messages with content: null and tool_calls are now accepted in both the Workers AI binding and REST API ( /v1/chat/completions ), fixing tool call round-trip failures.
[Bug fix] Streaming responses now correctly report finish_reason only on the usage chunk, matching OpenAI's streaming behavior and preventing duplicate finish events.
[Bug fix] /v1/chat/completions now preserves original tool call IDs from models instead of regenerating them.
Previously, the endpoint was generating new IDs which broke multi-turn tool calling because AI SDK clients could not match tool results to their original calls.
[Bug fix] /v1/chat/completions now correctly reports finish_reason: "tool_calls" in the final usage chunk when tools are used.
Previously, it was hardcoding finish_reason: "stop" which caused AI SDK clients to think the conversation was complete instead of executing tool calls.
2026-02-13 GLM-4.7-Flash, @cloudflare/tanstack-ai, and workers-ai-provider v3.1.1 @cf/zai-org/glm-4.7-flash is now available on Workers AI!
A fast and efficient multilingual text generation model optimized for multi-turn tool calling across 100+ languages.
Read changelog to get started.
New @cloudflare/tanstack-ai package for using Workers AI and AI Gateway with TanStack AI.
workers-ai-provider v3.1.1 adds transcription, text-to-speech, and reranking capabilities.
2026-01-28 Black Forest Labs FLUX.2 [klein] 9B now available @cf/black-forest-labs/flux-2-klein-9b now available on Workers AI!
Read changelog to get started 2026-01-15 Black Forest Labs FLUX.2 [klein] 4b now available @cf/black-forest-labs/flux-2-klein-4b now available on Workers AI!
Read changelog to get started 2025-12-03 Deepgram Flux promotional period over on Dec 8, 2025 - now has pricing Check out updated pricing on the @cf/deepgram/flux model page or pricing page Pricing will start Dec 8, 2025 2025-11-25 Black Forest Labs FLUX.2 dev now available @cf/black-forest-labs/flux-2-dev now available on Workers AI!
Read changelog to get started 2025-11-13 Qwen3 LLM and Embeddings available on Workers AI @cf/qwen/qwen3-30b-a3b-fp8 and @cf/qwen/qwen3-embedding-0.6b now available on Workers AI 2025-10-21 New voice and LLM models on Workers AI Deepgram Aura 2 brings new text-to-speech capabilities to Workers AI.
Check out @cf/deepgram/aura-2-en and @cf/deepgram/aura-2-es on how to use the new models.
IBM Granite model is also up!
This new LLM model is small but mighty, take a look at the docs for more @cf/ibm-granite/granite-4.0-h-micro 2025-10-02 Deepgram Flux now available on Workers AI We're excited to be a launch partner with Deepgram and offer their new Speech Recognition model built specifically for enabling voice agents.
Check out Deepgram's blog for more details on the release.
Access the model through @cf/deepgram/flux and check out the changelog for in-depth examples.
2025-09-24 New local models available on Workers AI We've added support for some regional models on Workers AI in support of uplifting local AI labs and AI sovereignty.
Check out the full blog post here .
@cf/pfnet/plamo-embedding-1b creates embeddings from Japanese text.
@cf/aisingapore/gemma-sea-lion-v4-27b-it is a fine-tuned model that supports multiple South East Asian languages, including Burmese, English, Indonesian, Khmer, Lao, Malay, Mandarin, Tagalog, Tamil, Thai, and Vietnamese.
@cf/ai4bharat/indictrans2-en-indic-1B is a translation model that can translate between 22 indic languages, including Bengali, Gujarati, Hindi, Tamil, Sanskrit and even traditionally low-resourced languages like Kashmiri, Manipuri and Sindhi.
2025-09-23 New document formats supported by Markdown conversion utility Our Markdown conversion utility now supports converting .docx and .odt files.
2025-09-18 Model Catalog updates (types, EmbeddingGemma, model deprecation) Workers AI types got updated in the upcoming wrangler release, please use npm i -D wrangler@latest to update your packages.
EmbeddingGemma model accuracy has been improved, we recommend re-indexing data to take advantage of the improved accuracy Some older Workers AI models are being deprecated on October 1st, 2025.
We reccommend you use the newer models such as Llama 4 and gpt-oss .
The following models are being deprecated: @hf/thebloke/zephyr-7b-beta-awq @hf/thebloke/mistral-7b-instruct-v0.1-awq @hf/thebloke/llama-2-13b-chat-awq @hf/thebloke/openhermes-2.5-mistral-7b-awq @hf/thebloke/neural-chat-7b-v3-1-awq @hf/thebloke/llamaguard-7b-awq @hf/thebloke/deepseek-coder-6.7b-base-awq @hf/thebloke/deepseek-coder-6.7b-instruct-awq @cf/deepseek-ai/deepseek-math-7b-instruct @cf/openchat/openchat-3.5-0106 @cf/tiiuae/falcon-7b-instruct @cf/thebloke/discolm-german-7b-v1-awq @cf/qwen/qwen1.5-0.5b-chat @cf/qwen/qwen1.5-7b-chat-awq @cf/qwen/qwen1.5-14b-chat-awq
@cf/tinyllama/tinyllama-1.1b-chat-v1.0 @cf/qwen/qwen1.5-1.8b-chat @hf/nexusflow/starling-lm-7b-beta @cf/fblgit/una-cybertron-7b-v2-bf16 2025-09-05 Introducing EmbeddingGemma from Google We’re excited to be a launch partner alongside Google to bring their newest embedding model to Workers AI.
We're excited to introduce EmbeddingGemma delivers best-in-class performance for its size, enabling RAG and semantic search use cases.
Take a look at @cf/google/embeddinggemma-300m for more details.
Now available to use for embedding in AI Search too.
2025-08-27 Introducing Partner models to the Workers AI catalog Read the blog for more details @cf/deepgram/aura-1 is a text-to-speech model that allows you to input text and have it come to life in a customizable voice @cf/deepgram/nova-3 is speech-to-text model that transcribes multilingual audio at a blazingly fast speed @cf/pipecat-ai/smart-turn-v2 helps you detect when someone is done speaking @cf/leonardo/lucid-origin is a text-to-image model that generates images with sharp graphic design, stunning full-HD renders, or highly specific creative direction @cf/leonardo/phoenix-1.0 is a
text-to-image model with exceptional prompt adherence and coherent text WebSocket support added for audio models like @cf/deepgram/aura-1 , @cf/deepgram/nova-3 , @cf/pipecat-ai/smart-turn-v2 2025-08-05 Adding gpt-oss models to our catalog Check out the blog for more details about the new models Take a look at the gpt-oss-120b and gpt-oss-20b model pages for more information about schemas, pricing, and context windows 2025-04-09 Pricing correction for @cf/myshell-ai/melotts We've updated our documentation to reflect the correct pricing for melotts: $0.0002 per audio minute, which is actually
cheaper than initially stated.
The documented pricing was incorrect, where it said users would be charged based on input tokens.
2025-03-17 Minor updates to the model schema for llama-3.2-1b-instruct, whisper-large-v3-turbo, llama-guard llama-3.2-1b-instruct - updated context window to the accurate 60,000 whisper-large-v3-turbo - new hyperparameters available llama-guard-3-8b - the messages array must alternate between user and assistant to function correctly 2025-02-21 Workers AI bug fixes We fixed a bug where max_tokens defaults were not properly being respected - max_tokens now correctly defaults to 256 as displayed on the model pages.
Users relying on the previous behaviour may observe this as a breaking change.
If you want to generate more tokens, please set the max_tokens parameter to what you need.
We updated model pages to show context windows - which is defined as the tokens used in the prompt + tokens used in the response.
If your prompt + response tokens exceed the context window, the request will error.
Please set max_tokens accordingly depending on your prompt length and the context window length to ensure a successful response.
2024-09-26 Workers AI Birthday Week 2024 announcements Meta Llama 3.2 1B, 3B, and 11B vision is now available on Workers AI @cf/black-forest-labs/flux-1-schnell is now available on Workers AI Workers AI is fast!
Powered by new GPUs and optimizations, you can expect faster inference on Llama 3.1, Llama 3.2, and FLUX models.
No more neurons.
Workers AI is moving towards unit-based pricing Model pages get a refresh with better documentation on parameters, pricing, and model capabilities Closed beta for our Run Any* Model feature, sign up here Check out the product announcements blog post for more information And the technical blog post if you want to learn about how we made Workers AI fast 2024-07-23 Meta Llama 3.1 now available on Workers AI Workers AI now suppoorts Meta Llama 3.1 .
2024-06-27 Introducing embedded function calling A new way to do function calling with Embedded function calling Published new @cloudflare/ai-utils npm package Open-sourced ai-utils on Github 2024-06-19 Added support for traditional function calling Function calling is now supported on enabled models Properties added on models page to show which models support function calling 2024-06-18 Native support for AI Gateways Workers AI now natively supports AI Gateway .
2024-06-11 Deprecation announcement for `@cf/meta/llama-2-7b-chat-int8` We will be deprecating @cf/meta/llama-2-7b-chat-int8 on 2024-06-30.
Replace the model ID in your code with a new model of your choice: @cf/meta/llama-3-8b-instruct is the newest model in the Llama family (and is currently free for a limited time on Workers AI).
@cf/meta/llama-3-8b-instruct-awq is the new Llama 3 in a similar precision to your currently selected model.
This model is also currently free for a limited time.
If you do not switch to a different model by June 30th, we will automatically start returning inference from @cf/meta/llama-3-8b-instruct-awq .
2024-05-29 Add new public LoRAs and note on LoRA routing Added documentation on new public LoRAs .
Noted that you can now run LoRA inference with the base model rather than explicitly calling the -lora version 2024-05-17 Add OpenAI compatible API endpoints Added OpenAI compatible API endpoints for /v1/chat/completions and /v1/embeddings .
For more details, refer to Configurations .
2024-04-11 Add AI native binding Added new AI native binding, you can now run models with const resp = await env.AI.run(modelName, inputs) Deprecated @cloudflare/ai npm package.
While existing solutions using the @cloudflare/ai package will continue to work, no new Workers AI features will be supported.
Moving to native AI bindings is highly recommended Previous Agents ↗ Was this helpful?
Yes No Edit page Report issue On this page Overview Edit page Report issue Getting started Plans Contact sales Partners Find a partner Startups Under attack?
Domain name search Company About Careers Investors Press Press kit Global network Public interest Project Galileo Athenian Project Cloudflare for Campaigns Project Fairshot Impact/ESG Compliance Compliance resources Trust Hub Data Protection Responsible AI Transparency report Report abuse Resources App innovation report Cloudflare Radar Case studies Status Support Events Blog Developers Documentation Learning center Community Solutions SSE and SASE platform Cloudflare AI Cloud AI Security Frontend Development Platform Multi-Tenant Platform Development Web Security Platform Start Building Log
In © 2026 Cloudflare, Inc.
Privacy policy | Report security issues | Terms of use | Trademark | Your privacy choices Docs
