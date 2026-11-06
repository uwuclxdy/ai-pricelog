> ## AI Agent Context > Get the complete documentation index at: https://aistudio.google.com/llms.txt > Use this file to discover all available pages.
> For the full documentation in a single file, fetch: https://aistudio.google.com/llms-full.txt # Release notes This page documents updates to the Gemini API.
## November 5, 2026 {% id="11-05-2026" %} * **Gemini Omni 1.2 Flash generally available (GA)**: Released [Gemini Omni 1.2 Flash](/docs/models/gemini-omni-flash) (`gemini-omni-1.2-flash`), featuring up to 15-second video generation and conversational editing (3 to 10 seconds for first and last frame interpolation, and 3 to 10 seconds per-turn video extension up to 30 seconds total length), improved character and subject consistency across up to 6 reference images, 30% lower video output [pricing](/docs/pricing#gemini-omni-1.2-flash) ($12.00 per 1M tokens), and doubled paid-tier [rate
limits](/docs/rate-limits#gemini-omni-flash-rate-limits).
See the [Gemini Omni Flash guide](/docs/omni) to get started.
* **Gemini Omni 1.1 Flash automatic routing notice**: Effective **December 3, 2026**, API requests to `gemini-omni-1.1-flash` will automatically route to `gemini-omni-1.2-flash` at [Gemini Omni 1.2 Flash rates](/docs/pricing#gemini-omni-1.2-flash).
* **Expanded Office and OpenDocument file support**: The Gemini API now accepts PowerPoint 97-2003 (PPT), OpenDocument Presentation (ODP), and OpenDocument Spreadsheet (ODS) files as input, and adds page-image processing for Word 97-2003 (DOC) files.
DOC, PPT, and ODP files are rendered as page images.
For ODS files, the model receives the data and formulas from the first sheet.
Processing for DOCX, DOTX, ODT, PPTX, XLSX, and XLS files is unchanged.
See [Office and OpenDocument files](/docs/document-processing#office-documents) for how each format is processed.
* **More file types and file URIs in function responses**: Tools can now return Office and OpenDocument files, audio, and video to the model.
* **GenerateContent API**: Function response parts now accept audio, video, and Office and OpenDocument files, in addition to images, PDFs, and plain text.
They also accept `fileData`, so tools can return a Files API URI instead of inline bytes.
`displayName` is now available on both `inlineData` and `fileData`, and video parts accept `mediaProcessing` (`STATIC` or `AGENTIC`).
* **Interactions API**: `function_result` steps now accept `document`, `audio`, and `video` content blocks, in addition to `text` and `image`, by inline `data` or `uri`.
Video blocks are available in `v1beta` and `v1alpha` and accept `processing`.
See [Multimodal function responses](/docs/function-calling#multimodal) for details.
## November 4, 2026 {% id="11-04-2026" %} * **Voice remixing for Gemini 3.8 TTS**: Released [Voice remixing](/docs/voice-remixing), which lets you modify an existing prebuilt or [designed](/docs/voice-design) voice using natural-language instructions to create a new, independent stored voice.
Use `POST /v1beta/voices` with `gemini-3.8-flash-tts` (or remix interactively in [Google AI Studio](https://aistudio.google.com/generate-speech)) to generate a `voice_...` ID, then synthesize speech with [Gemini 3.8 Flash TTS](/docs/models/gemini-3.8-flash-tts) or [Gemini 3.8 Flash-Lite TTS](/docs/models/gemini-3.8-flash-lite-tts).
See the [Voice remixing guide](/docs/voice-remixing) to get started.
## November 2, 2026 {% id="11-02-2026" %} * **Gemini 2.5 Pro deprecation**: [`gemini-2.5-pro`](/docs/models/gemini-2.5-pro) is [deprecated](/docs/deprecations#gemini-2.5-pro-models) and is no longer available to select in Google AI Studio.
Effective December 1, 2026, all API requests to `gemini-2.5-pro` will automatically route to [`gemini-3.8-flash`](/docs/models/gemini-3.8-flash) and be billed at [Gemini 3.8 Flash rates](/docs/pricing#gemini-3.8-flash).
Before December 1, 2026, update your model string to `gemini-3.8-flash` and review the [Gemini 3.8 Flash migration guide](/docs/whats-new-gemini-3.8#migrate-to-gemini-3-8-flash).
Breaking API changes include function calling and `thought_signature` validation, `thinking_level` replacing `thinking_budget`, and removed sampling parameters and prefilled model turns.
* **Gemini 2.5 Flash deprecation**: [`gemini-2.5-flash`](/docs/models/gemini-2.5-flash) is [deprecated](/docs/deprecations#gemini-2.5-flash-models) and is no longer available to select in Google AI Studio.
Effective December 1, 2026, all API requests to `gemini-2.5-flash` will automatically route to [`gemini-3.5-flash-lite`](/docs/models/gemini-3.5-flash-lite) and be billed at [Gemini 3.5 Flash-Lite rates](/docs/pricing#gemini-3.5-flash-lite).
Before December 1, 2026, update your model string to `gemini-3.5-flash-lite` and review the [Gemini 3.5 Flash-Lite migration guide](/docs/whats-new-gemini-3.6#migrate-to-gemini-3-5-flash-lite).
Breaking API changes include function calling and `thought_signature` validation, `thinking_level` replacing `thinking_budget`, and removed sampling parameters and prefilled model turns.
## October 30, 2026 {% id="10-30-2026" %} * **Computer Use generally available (GA)**: Released the [Computer Use](/docs/computer-use) tool to general availability (GA) across the Interactions and GenerateContent APIs.
## October 27, 2026 {% id="10-27-2026" %} * **Gemini API CLI (`gemini-api`) beta**: Released the [Gemini API CLI](/docs/cli) (`gemini-api`), a stateless, zero-dependency command-line client for AI coding agents, scripts, and CI pipelines.
Use `gemini-api` on the [Interactions API](/docs/interactions-overview) to generate text and media, analyze files, and run [Gemini managed agents](/docs/agents).
See the [Gemini API CLI guide](/docs/cli) to get started.
## October 26, 2026 {% id="10-26-2026" %} * **Generate Content API storage on by default**: New projects using the Generate Content API (`generateContent`, `streamGenerateContent`, and `batchGenerateContent`) on the paid tier now store requests by default (`store=true`), matching the Interactions API.
Existing projects keep their current setting.
To opt out, set `store=false` on individual requests or turn off Generate Content API logging in the **Settings** panel of the [Logs and Datasets](/logs) dashboard.
See [Logs and datasets](/docs/logs-datasets#configure-logging) for details.
## October 13, 2026 {% id="10-13-2026" %} * **Gemini 4 Argon (`gemini-4-argon`) generally available (GA)**: Released [Gemini 4 Argon](/docs/models/gemini-4-argon) (`gemini-4-argon`), our most capable model built for complex coding, agentic, math, and science tasks.
For API changes, pricing, and migration guidance, see [What's new in Gemini 4 Argon](/docs/latest-model).
## October 8, 2026 {% id="10-08-2026" %} * **Gemini 3.7 Flash deprecation**: [`gemini-3.7-flash`](/docs/whats-new-gemini-3.7) is deprecated and has been replaced by [`gemini-3.8-flash`](/docs/whats-new-gemini-3.8).
It is no longer available to select in Google AI Studio, and API requests to `gemini-3.7-flash` are automatically routed to `gemini-3.8-flash`.
Update your model string to `gemini-3.8-flash` and review the [Gemini 3.8 Flash guide](/docs/whats-new-gemini-3.8).
* **Gemini 3.5 Flash deprecation**: [`gemini-3.5-flash`](/docs/whats-new-gemini-3.5) is deprecated and has been replaced by [`gemini-3.6-flash`](/docs/whats-new-gemini-3.6).
It is no longer available to select in Google AI Studio, and API requests to `gemini-3.5-flash` are automatically routed to `gemini-3.6-flash`.
Update your model string to `gemini-3.6-flash` (or [`gemini-3.8-flash`](/docs/whats-new-gemini-3.8)) and review the [Gemini 3.6 Flash guide](/docs/whats-new-gemini-3.6).
* **Deep Research Agent `deep-research-pro-preview-12-2025` deprecation**: The `deep-research-pro-preview-12-2025` agent is deprecated and will be [shut down](/docs/deprecations#managed-agents) on **October 23, 2026**.
Migrate your requests to one of the newer [Deep Research](/docs/deep-research) agent versions: * [`deep-research-preview-04-2026`](/docs/models/deep-research-preview-04-2026): Designed for speed and efficiency, ideal to be streamed back to a client UI.
* [`deep-research-max-preview-04-2026`](/docs/models/deep-research-max-preview-04-2026): Maximum comprehensiveness for automated context gathering and synthesis.
To migrate, update the `agent` parameter in your `interactions.create` requests from `deep-research-pro-preview-12-2025` to `deep-research-preview-04-2026` (or `deep-research-max-preview-04-2026`).
## October 6, 2026 {% id="10-06-2026" %} * **Gemini Nano Banana 2.1 generally available (GA)**: Released [Gemini Nano Banana 2.1](/docs/models/gemini-nano-banana-2.1) (`gemini-nano-banana-2.1`), the latest high-efficiency image generation and conversational editing model.
An update to Nano Banana 2 ([`gemini-3.1-flash-image`](/docs/models/gemini-3.1-flash-image)), it maintains Flash-level speed and cost efficiency while delivering significant improvements in visual quality, prompt adherence, multi-turn character consistency, text rendering, and wide and panoramic aspect ratio generation (`1:4`, `4:1`, `1:8`, `8:1`) across `1K`, `2K`, and `4K` resolutions.
See the [Image generation guide](/docs/image-generation) to get started.
* **Deprecation announcement**: The `gemini-3.1-flash-image` model is deprecated (no shutdown date announced).
Migrate to [`gemini-nano-banana-2.1`](/docs/models/gemini-nano-banana-2.1).
## September 22, 2026 {% id="09-22-2026" %} * **Gemini 3.8 Flash TTS and Gemini 3.8 Flash-Lite TTS generally available (GA)**: Released our next-generation text-to-speech (TTS) audio models and the Gemini API Voices endpoint (`/v1beta/voices`): * **[Gemini 3.8 Flash TTS](/docs/models/gemini-3.8-flash-tts) (`gemini-3.8-flash-tts`)**: Flagship creative TTS model engineered for studio-grade voice fidelity, nuanced acting, regional dialects, and long-form multi-turn stability.
* **[Gemini 3.8 Flash-Lite TTS](/docs/models/gemini-3.8-flash-lite-tts) (`gemini-3.8-flash-lite-tts`)**: Fast, cost-efficient TTS model built to replace `gemini-3.1-flash-tts-preview` for high-throughput production and real-time voice agent cascades.
* **[Voice design](/docs/voice-design), [Voice replication](/docs/voice-replication), and the [Extended Voice Library](/docs/speech-generation#voice-library)**: Create persistent custom vocal personas from text prompts, replicate voices with consent verification, and query 150+ prebuilt and custom voices.
See the [Text-to-speech guide](/docs/speech-generation) to get started.
## September 18, 2026 {% id="09-18-2026" %} * **Gemini 2.5 models access update**: To ensure reliable performance for everyone, we are limiting access to the 2.5 models to users who have actively used them in the past.
These models are not deprecated and will continue to be served until further notice through the API.
For any new projects, use our latest models: 3.5 Flash-Lite or 3.8 Flash.
This helps us maintain sufficient capacity for both ongoing legacy workflows and new applications.
## September 17, 2026 {% id="09-17-2026" %} * **Antigravity Agent 09-2026**: Released `antigravity-preview-09-2026`, which replaces and deprecates `antigravity-preview-05-2026`.
If you run on a remote sandbox (`environment: "remote"`) and read only `output_text` or `model_output` steps, update the agent string and nothing else changes.
If you run tools locally (`local_environment`) or parse `function_call` steps, the built-in tools changed.
Parameters use PascalCase instead of snake_case, and file edits use line-range replacements instead of full rewrites.
| Capability | 05-2026 | 09-2026 | | :--- | :--- | :--- | | File creation | `write_file(path, content)` | `write_to_file(TargetFile, CodeContent, Overwrite, Description)` | | File editing | `write_file(path, content)`, full rewrite | `replace_file_content(TargetFile, StartLine, EndLine, TargetContent, ReplacementContent)` | | File reading | `read_file(path, offset, limit)`, byte offsets | `view_file(AbsolutePath, StartLine, EndLine, ContentOffset)` | | Directory listing | `list_files(path)` | `list_dir(DirectoryPath)` | | File and code search | None, agents used shell commands |
`find_by_name(SearchDirectory, Pattern, MaxDepth)` and `grep_search(SearchPath, Query, IsRegex)` | | Shell execution | `code_execution(command, timeout_seconds)` | Unchanged | | Web search | `google_search(queries)` | Unchanged | See the [Antigravity Agent](/docs/antigravity-agent) guide.
`antigravity-preview-05-2026` shuts down on October 5, 2026, tracked on the [deprecations](/docs/deprecations#managed-agents) page.
## September 15, 2026 {% id="09-15-2026" %} * **Gemini 3.8 Live and Gemini 3.8 Live Extended Thinking generally available (GA)**: Released our next-generation Live API models for real-time multimodal dialogue and agentic tool use: * **[Gemini 3.8 Live](/docs/models/gemini-3.8-live) (`gemini-3.8-live`)**: Engineered for sub-second conversational latency with native audio understanding, affective dialogue, proactive audio, and synchronous/asynchronous function calling.
* **[Gemini 3.8 Live Extended Thinking](/docs/models/gemini-3.8-live-extended-thinking) (`gemini-3.8-live-extended-thinking`)**: Specialized for complex reasoning, multi-step planning, and long-horizon state tracking with configurable thinking levels (`MINIMAL`, `LOW`, `MEDIUM`, `HIGH`) and asynchronous function calling.
To get started, see the [Thinking in the Live API guide](/docs/live-api/thinking) and the [Live API overview](/docs/live-api).
## September 3, 2026 {% id="09-03-2026" %} * **Lyria 3.5 generally available (GA)**: Released the next generation of Google's music generation model: * [`lyria-3.5`](/docs/models/lyria-3.5): Full-length song generation with improved musical coherence, natural vocals, and fine-grained duration and structural control.
The model supports text and image inputs and generates high-fidelity 44.1 kHz stereo audio.
See the [Music generation](/docs/music-generation) guide for details and code samples.
## September 2, 2026 {% id="09-02-2026" %} * **Gemini 3.8 Flash generally available (GA)**: Released `gemini-3.8-flash`, our most intelligent Flash model, engineered for long-horizon software engineering, autonomous agents, and complex enterprise workflows.
To get started, see the [Gemini 3.8 Flash](/docs/models/gemini-3.8-flash) model page and the [Gemini 3.8 Flash guide](/docs/whats-new-gemini-3.8).
## September 1, 2026 {% id="09-01-2026" %} * **Agentic video understanding**: Released agentic video understanding for Gemini 3.7 Flash, 3.6 Flash, and 3.5 Flash-Lite across the Interactions and GenerateContent APIs.
The model dynamically navigates video timelines, requesting transcripts, frames, or audio tracks on demand.
This approach uses up to 88% fewer tokens for long-form content compared to static processing.
To get started, see the [Agentic video understanding](/docs/video-understanding#agentic-video-understanding) guide.
## August 27, 2026 {% id="08-27-2026" %} * **Gemini Omni Flash generally available (GA)**: Released `gemini-omni-1.1-flash`, the GA version of our fast, conversational video generation and editing model.
This release includes significant new capabilities: * **Video extension**: Seamlessly extend existing videos by generating continuations at the end of a clip using the `extend` task or directly with a prompt.
* **Interpolation (first + last frame)**: Generate a video transitioning between two images using the `image_to_video` task with up to 2 images.
* **Resolution control**: New `resolution` parameter in `video_config` supports `360p`, `720p` (default), `1080p`, and `4k` outputs.
1080p and 4K outputs are generated using upscaling.
The existing `gemini-omni-flash-preview` endpoint will be deprecated on September 30, 2026.
To get started, see the [Gemini Omni Flash](/docs/models/gemini-omni-flash) model page and the [omni guide](/docs/omni).
## August 26, 2026 {% id="08-26-2026" %} * **Gemini 3.5 Transcribe generally available (GA)**: Released two dedicated speech-to-text models based on Gemini's audio understanding: * **Gemini 3.5 Transcribe** (`gemini-3.5-transcribe`): High-accuracy, low-latency non-streaming speech-to-text with utterance-based language detection across 80+ languages, speaker diarization, word-level timestamps, and custom vocabulary biasing (up to 1,000 terms).
* **Gemini 3.5 Transcribe Live** (`gemini-3.5-transcribe-live`): Low-latency, bidirectional streaming speech-to-text over WebSockets using the Live API, supporting interim and finalized transcription events, Smart transcription mode, and multiple Voice Activity Detection (VAD) strategies.
To get started, see the [Audio transcription guide](/docs/transcribe), the [Live transcription guide](/docs/live-api/live-transcribe), and the [Gemini 3.5 Transcribe model page](/docs/models/gemini-3.5-transcribe).
## August 13, 2026 {% id="08-13-2026" %} * **Gemini 3.7 Flash generally available (GA)**: Released our most intelligent workhorse model yet for coding and agents: * **Gemini 3.7 Flash** (`gemini-3.7-flash`): Substantial improvements across software engineering, web development, and agentic workflows, available at an introductory price through December 31, 2026.
To get started, see the [Gemini 3.7 Flash](/docs/models/gemini-3.7-flash) model page and the [Latest model guide](/docs/latest-model).
## July 30, 2026 {% id="07-30-2026" %} * **Gemini Robotics ER 2 in public preview**: Released two new embodied reasoning model endpoints for robotics: * `gemini-robotics-er-2-preview`: Advanced spatial reasoning, agentic code execution, multi-step tool orchestration, video moment finding, progress classification, and multi-robot coordination.
* `gemini-robotics-er-2-streaming-preview`: Optimized for real-time text streaming using the Live API, enabling low-latency robot agents with bidirectional audio and video input.
Both model endpoints accept text, image, video, and audio inputs and support function calling with blocking behavior for physical robot actions.
To get started, see the [Gemini Robotics ER overview](/docs/robotics-overview).
For real-time streaming use cases, see [Robotics with streaming](/docs/robotics-streaming).
* **Deprecation announcement**: The `gemini-robotics-er-1.6-preview` model will be [shut down](/docs/deprecations) on August 31, 2026.
## July 21, 2026 {% id="07-21-2026" %} * **Gemini 3.6 Flash and Gemini 3.5 Flash-Lite generally available (GA)**: Released stable, production-ready versions of our latest 3.x Flash models: * **Gemini 3.6 Flash** (`gemini-3.6-flash`): Features improved token efficiency and code/agentic planning capabilities at a lower price point than 3.5 Flash, resolving developer feedback around output verbosity.
* **Gemini 3.5 Flash-Lite** (`gemini-3.5-flash-lite`): Offers a low-latency, highly cost-effective subagent option designed for high-volume automation.
To learn more, see the [Gemini 3.6 Flash guide](/docs/whats-new-gemini-3.6).
* **Deprecated parameters**: The sampling parameters `temperature`, `top_p` and `top_k` are now deprecated.
See the [Gemini 3.6 Flash guide](/docs/whats-new-gemini-3.6#sampling-parameter-deprecation) for details.
## July 6, 2026 {% id="07-06-2026" %} * [Developer logs](/docs/logs-datasets) support for the Interactions API: logs for supported Interactions API calls are now viewable in the [AI Studio dashboard](https://aistudio.google.com/logs).
## June 30, 2026 {% id="06-30-2026" %} * **Gemini Omni Flash in public preview**: Released `gemini-omni-flash-preview`, a high-performance multimodal model designed for high-speed video generation and conversational video editing.
Using the [Interactions API](/docs/interactions-overview), you can generate 3–10 second videos at 720p from text descriptions or animate still images, and then conversationally edit and refine the outputs.
To get started, see the [Gemini Omni Flash](/docs/omni) guide and the [Gemini Omni Flash](/docs/models/gemini-omni-flash) model card.
* Released `gemini-3.1-flash-lite-image` (Nano Banana 2 Lite) to general availability (GA), our built-in multimodal model optimized for ultra-low latency and cost-effective image generation and editing.
See the [Gemini 3.1 Flash Lite Image](/docs/models/gemini-3.1-flash-lite-image) model card and the [Image generation](/docs/image-generation) guide.
## June 24, 2026 {% id="06-24-2026" %} * **Computer Use**: Launched public preview support for the [Computer Use](/docs/computer-use) tool in Gemini 3.5 Flash.
This release includes simplified actions with intents, built-in support for browser, mobile, and desktop environments, configurable safety policies, and advanced prompt injection detection.
## June 17, 2026 {% id="06-17-2026" %} * **Streaming support for speech generation**: Streaming via `streamGenerateContent` (and `stream: true` in the Interactions API) is now supported for the `gemini-3.1-flash-tts-preview` model.
To learn more, see the [Text-to-Speech](/docs/speech-generation#streaming) guide.
## June 15, 2026 {% id="06-15-2026" %} * **Deprecation announcement**: The following image generation models are being deprecated and will be [shut down](/docs/deprecations) on **August 17, 2026**: * **Imagen 4 and Gemini 3 Image models**: * `imagen-4.0-generate-001` * `imagen-4.0-ultra-generate-001` * `imagen-4.0-fast-generate-001` To migrate your code to newer stable or preview endpoints, refer to the [Gemini deprecations](/docs/deprecations#imagen-models) page.
* **Deprecation announcement**: The following video generation models are being deprecated and will be [shut down](/docs/deprecations) on **June 30, 2026**: * **Veo models**: * `veo-2.0-generate-001` * `veo-3.0-generate-001` * `veo-3.0-fast-generate-001` Update your integration to either use the Veo 3.1 preview model IDs (`veo-3.1-generate-preview`, `veo-3.1-fast-generate-preview`) or the 3.1 GA models available through the [Gemini Enterprise Agent Platform](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/veo/3-1-generate) to avoid service interruptions.
* **Deprecation announcement**: The experimental GMP Contextual View tool (a fixed interface for Grounding with Google Maps outputs) will [shut down](/docs/deprecations) on **June 15, 2026**: ## June 1, 2026 {% id="06-01-2026" %} * The following Gemini 2.0 models are now [shut down](/docs/deprecations): * `gemini-2.0-flash` * `gemini-2.0-flash-001` * `gemini-2.0-flash-lite` * `gemini-2.0-flash-lite-001` Use [`gemini-3.5-flash`](/docs/models/gemini-3.5-flash) or [`gemini-3.1-flash-lite`](/docs/models/gemini-3.1-flash-lite) instead.
## May 28, 2026 {% id="05-28-2026" %} * Released `gemini-3.1-flash-image` (Nano Banana 2) and `gemini-3-pro-image` (Nano Banana Pro), the generally available (GA) versions of our native visual models, [Gemini 3.1 Flash Image](/docs/models/gemini-3.1-flash-image) and [Gemini 3 Pro Image](/docs/models/gemini-3-pro-image).
* **Video-to-image generation support**: You can now pass a video file (via direct upload or as a public YouTube URL) as multimodal context alongside a text prompt to generate high-quality thumbnails, cinematic movie posters, or summary infographics.
This feature is supported exclusively on the `gemini-3.1-flash-image` model.
To learn more, see the [Video-to-image generation](/docs/image-generation#video-to-image) guide.
* Deprecation announcement: The `gemini-3.1-flash-image-preview` and `gemini-3-pro-image-preview` models are deprecated and will be [shut down](/docs/deprecations) on June 25, 2026.
## May 25, 2026 {% id="05-25-2026" %} * The `gemini-3.1-flash-lite-preview` model has been [shut down](/docs/deprecations).
Use [`gemini-3.1-flash-lite`](/docs/models/gemini-3.1-flash-lite) instead.
## May 19, 2026 {% id="05-19-2026" %} * Released `gemini-3.5-flash`, the generally available (GA) version of [Gemini 3.5 Flash](/docs/models/gemini-3.5-flash), our most intelligent model for sustained frontier performance on agentic and coding tasks.
* Launched the **Managed Agents in the Gemini API** in public preview.
This enables developers to build and deploy autonomous, stateful agents that run in secure, isolated Google-hosted Linux sandbox environments.
To learn more, see the [Agents overview](/docs/agents) page and the [Quickstart](/docs/managed-agents-quickstart).
* Released the general-purpose **Antigravity Agent** managed agent, [`antigravity-preview-05-2026`](/docs/models/antigravity-preview-05-2026), in public preview.
The Antigravity agent can autonomously plan, reason, write and execute code, manage files, and browse the web inside its sandbox container.
See the [Antigravity Agent](/docs/antigravity-agent) guide for code samples and specifications.
## May 7, 2026 {% id="05-07-2026" %} * Released `gemini-3.1-flash-lite`, the generally available (GA) version of [Gemini 3.1 Flash-Lite](/docs/models/gemini-3.1-flash-lite), optimized for speed, scale, and cost efficiency.
* Deprecation announcement: The `gemini-3.1-flash-lite-preview` model is deprecating on 5/11/26 and will be [shut down](/docs/deprecations) on May 25, 2026.
## May 6, 2026 {% id="05-06-2026" %} * **Upcoming breaking change**: The [Interactions API](/docs/interactions-overview) request and response schema (`outputs` → `steps`) and output format configuration (`response_format`) are changing.
The new schema becomes the default on **May 26** and the legacy schema will be removed on **June 8**.
See the [migration guide](/docs/interactions-breaking-changes-may-2026) for details.
## May 5, 2026 {% id="05-05-2026" %} * Updated **File Search** to support multimodal search.
You can now natively embed and search through images using the `gemini-embedding-2` model.
Grounding metadata now includes `media_id` for visual citations and `page_numbers` that indicate where information is found.
To learn more, see the [File Search](/docs/file-search) guide.
## May 4, 2026 {% id="05-04-2026" %} * Launched event-driven [Webhooks](/docs/webhooks) support in the Gemini API to replace polling workflows for the Batch API and long-running operations.
## April 30, 2026 {% id="04-30-2026" %} * The `gemini-robotics-er-1.5-preview` model has been [shut down](/docs/deprecations).
Use [`gemini-robotics-er-1.6-preview`](/docs/models/gemini-robotics-er-1.6-preview) instead.
## April 22, 2026 {% id="04-22-2026" %} * Released `gemini-embedding-2` as generally available (GA).
To learn more, see the [Embeddings](/docs/embeddings) page.
## April 21, 2026 {% id="04-21-2026" %} * Released new versions of the [Deep Research](/docs/deep-research) agent with collaborative planning, visualization support, MCP server integration, and File Search: * [`deep-research-preview-04-2026`](/docs/models/deep-research-preview-04-2026): Designed for speed and efficiency, ideal to be streamed back to a client UI.
* [`deep-research-max-preview-04-2026`](/docs/models/deep-research-max-preview-04-2026): Maximum comprehensiveness for automated context gathering and synthesis.
## April 15, 2026 {% id="04-15-2026" %} * Launched [Gemini 3.1 Flash TTS Preview](/docs/models/gemini-3.1-flash-tts-preview), our cost-efficient, expressive, and steerable text to speech model.
Read the [Text-to-Speech](/docs/speech-generation) docs to learn more.
## April 14, 2026 {% id="04-14-2026" %} * Released `gemini-robotics-er-1.6-preview`, our updated robotics model.
It now has new capabilities like instrument reading, improved spatial and physical reasoning capabilities.
To learn more, see [Gemini Robotics-ER](/docs/robotics-overview) page and the [blog](https://deepmind.google/blog/gemini-robotics-er-1-6).
* Deprecation announcement: The `gemini-robotics-er-1.5-preview` model will be [shut down](/docs/deprecations) on April 30, 2026 at 9AM PST.
## April 2, 2026 {% id="04-02-2026" %} * Released `gemma-4-26b-a4b-it` and `gemma-4-31b-it`, available on [AI Studio](https://aistudio.google.com) and through the Gemini API, as part of the [Gemma 4](https://ai.google.dev/gemma/docs/core) launch.
## April 1, 2026 {% id="04-01-2026" %} * Introduced the new [Flex](/docs/flex-inference) and [Priority](/docs/priority-inference) inference tiers, offering more options for optimizing cost or latency.
## March 31, 2026 {% id="03-31-2026" %} * Launched Veo 3.1 Lite Preview, [`veo-3.1-lite-generate-preview`](/docs/models/veo-3.1-lite-generate-preview), our most cost-efficient [video generation](/docs/video) model, designed for rapid iteration and building high-volume applications.
* The `gemini-2.5-flash-lite-preview-09-2025` model has been shut down.
Use [`gemini-3.1-flash-lite-preview`](/docs/models/gemini-3.1-flash-lite-preview) instead.
## March 26, 2026 {% id="03-26-2026" %} * Released [`gemini-3.1-flash-live-preview`](/docs/models/gemini-3.1-flash-live-preview), the latest audio-to-audio (A2A) model designed for real-time dialogue and voice-first AI applications.
Read the [Live API](/docs/live-api) docs to get started.
## March 25, 2026 {% id="03-25-2026" %} * Launched [Lyria 3](/docs/music-generation) music generation models: [`lyria-3-clip-preview`](/docs/models/lyria-3-clip-preview) (30-second clips) and [`lyria-3-pro-preview`](/docs/models/lyria-3-pro-preview) (full-length songs).
Both models accept text and image inputs and generate high-quality, 48kHz stereo audio.
See the [Music generation](/docs/music-generation) guide for details and code samples.
## March 23, 2026 {% id="03-23-2026" %} * Rolled out [Prepay and Postpay billing plans](/docs/billing) in AI Studio.
Existing accounts may be affected; read the [Billing](/docs/billing) documentation for more information.
## March 18, 2026 {% id="03-18-2026" %} * Released the new [Built-in Tools and Function Calling Combination](/docs/tool-combination) feature, making it possible to use Gemini's built-in tools alongside custom function calling tools in a single API call.
* [Grounding with Google Maps](/docs/maps-grounding#supported-models) is now supported for Gemini 3 models going forward.
## March 16, 2026 {% id="03-16-2026" %} * Introduced revamped [Usage Tiers](/docs/billing#about-billing) and [Billing Account spend caps](/docs/billing#tier-spend-caps) for a better user billing experience.
## March 12, 2026 {% id="03-12-2026" %} * Introduced [project-level spend caps](/docs/billing#project-spend-caps) to billing in AI Studio.
## March 10, 2026 {% id="03-10-2026" %} * Released `gemini-embedding-2-preview`, our first multimodal embedding model.
It supports text, image, video, audio, and PDF inputs, mapping all modalities into a unified embedding space.
To learn more, see [Embeddings](/docs/embeddings).
* Deprecation announcement: The `gemini-2.5-flash-lite-preview-09-2025` model will be [shut down](/docs/deprecations) on March 31, 2026.
## March 9, 2026 {% id="03-09-2026" %} * The Gemini 3 Pro Preview model has been [shut down](/docs/deprecations).
The `gemini-3-pro-preview` now points to [`gemini-3.1-pro-preview`](/docs/models/gemini-3.1-pro-preview).
## March 3, 2026 {% id="03-03-2026" %} * Launched Gemini 3.1 Flash-Lite Preview, the first Flash-Lite model in the Gemini 3 series.
Read the [model page](/docs/models/gemini-3.1-flash-lite-preview) for specs, specific updates, and developer guidance.
## February 26, 2026 {% id="02-26-2026" %} * Launched Nano Banana 2, [Gemini 3.1 Flash Image Preview](/docs/models/gemini-3.1-flash-image), a high-efficiency model optimized for speed and high-volume use cases.
* Deprecation announcement: Gemini 3 Pro Preview (`gemini-3-pro-preview`) will be [shut down](/docs/deprecations) March 9, 2026.
## February 19, 2026 {% id="02-19-2026" %} * Released [Gemini 3.1 Pro Preview](/docs/models/gemini-3.1-pro-preview), our latest iteration in the new Gemini 3 series family.
* Launched a separate endpoint `gemini-3.1-pro-preview-customtools`, which is better at prioritizing custom tools, for users building with a mix of bash and tools.
## February 18, 2026 {% id="02-18-2026" %} * Deprecation announcement: The following models will be [shut down](/docs/deprecations) June 1, 2026: * `gemini-2.0-flash` * `gemini-2.0-flash-001` * `gemini-2.0-flash-lite` * `gemini-2.0-flash-lite-001` ## February 17, 2026 {% id="02-17-2026" %} * The following models are [shut down](/docs/deprecations): * `gemini-2.5-flash-preview-09-25` * `imagen-4.0-generate-preview-06-06` * `imagen-4.0-ultra-generate-preview-06-06` ## January 29, 2026 {% id="01-29-2026" %} * Launched support for the Computer Use tool in `gemini-3-pro-preview` and
`gemini-3-flash-preview`.
## January 21, 2026 {% id="01-21-2026" %} * Changed the `latest` aliases: * `gemini-pro-latest` switched to `gemini-3-pro-preview` * `gemini-flash-latest` switched to `gemini-3-flash-preview` ## January 15, 2026 {% id="01-15-2026" %} * Deprecation announcement: The following models will be [shut down](/docs/deprecations) February 17, 2026: * `gemini-2.5-flash-preview-09-25` * `imagen-4.0-generate-preview-06-06` * `imagen-4.0-ultra-generate-preview-06-06` * The `gemini-2.5-flash-image-preview` model has been shut down.
## January 14, 2026 {% id="01-14-2026" %} * The `text-embedding-004` model has been [shut down](/docs/deprecations).
## January 13, 2026 {% id="01-13-2026" %} * Added 4k output resolutions for [Veo](/docs/video) and more support for portrait videos in all resolutions.
## January 12, 2026 {% id="01-12-2026" %} * Launched model lifecycle feature.
Some models will now specify the lifecycle stage and deprecation timeline.
See the following documentation for more information: * [Model stages](https://ai.google.dev/api/generate-content#ModelStatus) ## January 8, 2026 {% id="01-08-2026" %} * Launched support for Cloud Storage buckets and any public and private DB pre-signed URL as data input source for the Gemini API.
The file size limit has also increased from 20MB to 100MB.
For details, see [File input methods guide](/docs/file-input-methods).
## December 19, 2025 {% id="12-19-2025" %} * Introduced a breaking change to the Interactions API in v1beta.
The `total_reasoning_tokens` field has been renamed to `total_thought_tokens` to better align with the concept of "thoughts" in thinking models.
## December 17, 2025 {% id="12-17-2025" %} * Launched Gemini 3 Flash Preview, `gemini-3-flash-preview`, delivering fast frontier-class performance that rivals larger models at a fraction of the cost.
With upgraded visual and spatial reasoning, and agentic coding capabilities.
Read the documentation on some new features, including: * [Multimodal function responses](/docs/function-calling#multimodal) * [Code execution with images](/docs/code-execution#images) ## December 12, 2025 {% id="12-12-2025" %} * Released `gemini-2.5-flash-native-audio-preview-12-2025`, a new native audio model for the Live API.
This update improves the model's ability to handle complex workflows.
To learn more, see the [Live API guide](/docs/live-api/capabilities) and [Gemini 2.5 Flash Native Audio](/docs/models/gemini-2.5-flash-native-audio-preview-12-2025).
## December 11, 2025 {% id="12-11-2025" %} * Launched the Interactions API.
This API provides a unified interface for interacting with Gemini models and agents.
To learn more, see the [Interactions API](/docs/interactions-overview) guide.
* Launched the Gemini Deep Research agent in preview.
It can autonomously plan, execute, and synthesize results for multi-step research tasks.
See the [Deep Research](/docs/deep-research) guide for details.
## December 10, 2025 {% id="12-10-2025" %} * Launched enhancements to our [text-to-speech models](/docs/speech-generation), Gemini 2.5 Flash TTS preview (optimized for low latency) and Gemini 2.5 Pro TTS preview (optimized for quality), including enhanced expressivity, precision pacing, and seamless dialogue.
## December 9, 2025 {% id="12-09-2025" %} * The following Gemini Live API models are now shut down: - `gemini-2.0-flash-live-001` - `gemini-live-2.5-flash-preview` ## December 5, 2025 {% id="12-05-2025" %} * Gemini 3 billing for [Grounding with Google Search](/docs/google-search) will begin on January 5, 2026.
## December 4, 2025 {% id="12-04-2025" %} * Deprecation announcement: The `gemini-2.5-flash-image-preview` model will be shut down January 15, 2026.
## December 3, 2025 {% id="12-03-2025" %} * Deprecation announcement: The `text-embedding-004` model will be shut down January 14, 2026.
## November 20, 2025 {% id="11-20-2025" %} * Released Gemini 3 Pro Image Preview, `gemini-3-pro-image-preview`, the next iteration to the Nano Banana model.
Read the [Image generation](/docs/image-generation) page for more details.
## November 18, 2025 {% id="11-18-2025" %} * Launched the first Gemini 3 series model, `gemini-3-pro-preview`, our state-of-the-art reasoning and multimodal understanding model with powerful agentic and coding capabilities.
In addition to improvements in intelligence and performance, Gemini 3 Pro Preview introduces new behavior around: * [Media resolution](/docs/media-resolution) * [Thought signatures](/docs/thinking#signatures) * [Thinking levels](/docs/thinking#thinking-levels) Read the Gemini 3 Developer Guide for migration, new features, and specs.
## November 11, 2025 {% id="11-11-2025" %} * Deprecation announcement: The following models will be shut down: * November 12: - `veo-3.0-fast-generate-preview` - `veo-3.0-generate-preview` * November 14: - `gemini-2.0-flash-exp-image-generation` - `gemini-2.0-flash-preview-image-generation` ## November 10, 2025 {% id="11-10-2025" %} * The following model is shut down: - `imagen-3.0-generate-002` Use [Imagen 4](/docs/image-generation) instead.
Refer to the [Gemini deprecations table](/docs/deprecations) for more details.
## November 6, 2025 {% id="11-06-2025" %} * Launched the File Search API to public preview, enabling developers to ground responses in their own data.
Read the new [File Search](/docs/file-search) page for more info.
## November 4, 2025 {% id="11-04-2025" %} * For [Gemini 2.5 Flash Image](/docs/image-generation), the input token count for images has been reduced from 1290 to 258, lowering the cost of image editing.
* Deprecation announcement: The following models will be shut down: * November 18th: - `gemini-2.5-flash-lite-preview-06-17` - `gemini-2.5-flash-preview-05-20` * December 2nd: - `gemini-2.0-flash-thinking-exp` - `gemini-2.0-flash-thinking-exp-01-21` - `gemini-2.0-flash-thinking-exp-1219` - `gemini-2.5-pro-preview-03-25` - `gemini-2.5-pro-preview-05-06` - `gemini-2.5-pro-preview-06-05` * December 9th: - `gemini-2.0-flash-lite-preview` - `gemini-2.0-flash-lite-preview-02-05` - `gemini-2.0-flash-exp` - `gemini-2.0-pro-exp` - `gemini-2.0-pro-exp-02-05` ## October 29, 2025 {% id="10-29-2025" %} *
Launched the new [logging and datasets](/docs/logs-datasets) tool for the Gemini API.
## October 20, 2025 {% id="10-20-2025" %} * The following Gemini Live API models are now shut down: - `gemini-2.5-flash-preview-native-audio-dialog` - `gemini-2.5-flash-exp-native-audio-thinking-dialog` You can use `gemini-2.5-flash-native-audio-preview-09-2025` instead.
* Deprecation announcement: Shut down for `gemini-2.0-flash-live-001` and `gemini-live-2.5-flash-preview` coming December 09, 2025.
## October 17, 2025 {% id="10-17-2025" %} * **Grounding with Google Maps** is now generally available.
For more information, see [Grounding with Google Maps](/docs/maps-grounding) documentation.
## October 15, 2025 {% id="10-15-2025" %} * Released [Veo 3.1 and 3.1 Fast](/docs/video) models in public preview, with new features including: - Extending Veo-created videos.
- Referencing up to three images to generate a video.
- Providing first and last frame images to generate videos from.
This launch also added more options for Veo 3 output video durations: 4, 6, and 8 seconds.
* Deprecation announcement: Shut down for `veo-3.0-generate-preview` and `veo-3.0-fast-generate-preview` coming November 12, 2025.
## October 7, 2025 {% id="10-07-2025" %} * Launched [Gemini 2.5 Computer Use Preview](/docs/computer-use) ## October 2, 2025 {% id="10-02-2025" %} * Launched Gemini 2.5 Flash Image GA: [Image Generation with Gemini](/docs/image-generation) ## September 29, 2025 {% id="09-29-2025" %} * The following Gemini 1.5 models are now shut down: - `gemini-1.5-pro` - `gemini-1.5-flash-8b` - `gemini-1.5-flash` ## September 25, 2025 {% id="09-25-2025" %} * Released Gemini Robotics-ER 1.5 model in preview.
See the [Robotics overview](/docs/robotics-overview) to learn about how to use the model for your robotics application.
* Launched following preview models: - `gemini-2.5-flash-preview-09-2025` - `gemini-2.5-flash-lite-preview-09-2025` See the [Models](/docs/models) page for details.
## September 23, 2025 {% id="09-23-2025" %} * Released `gemini-2.5-flash-native-audio-preview-09-2025`, a new native audio model for the Live API with improved function calling and speech cut off handling.
To learn more, see the [Live API guide](/docs/live-api/capabilities) and [Gemini 2.5 Flash Native Audio](/docs/models).
## September 16, 2025 {% id="09-16-2025" %} * Deprecation announcement: The following models will be shut down in October 2025: - `embedding-001` - `embedding-gecko-001` - `gemini-embedding-exp-03-07` (`gemini-embedding-exp`) See the [Embeddings](/docs/embeddings) page for details on the latest embeddings model.
## September 10, 2025 {% id="09-10-2025" %} * Released support for the [Embeddings model in Batch API](/docs/batch-api#batch-embedding), and added Batch API to the [OpenAI compatibility library](/docs/openai#batch) for even easier ways to get started with batch queries.
## September 9, 2025 {% id="09-09-2025" %} * Launched Veo 3 and Veo 3 Fast GA, with lower pricing and new options for aspect ratios, resolution, and seeding.
Read the [Veo documentation](/docs/video) for more information.
## August 26, 2025 {% id="08-26-2025" %} * Launched [Gemini 2.5 Image Preview](/docs/models), our latest native image generation model.
## August 18, 2025 {% id="08-18-2025" %} * Released [URL context tool](/docs/url-context) to general availability (GA), a tool for providing URLs as additional context to prompts.
Support for using URL context with the `gemini-2.0-flash` model (available during experimental release) will be discontinued in one week.
## August 14, 2025 {% id="08-14-2025" %} * Released Imagen 4 Ultra, Standard and Fast models as generally available (GA).
To learn more, see the [Imagen](/docs/image-generation) page.
## August 7, 2025 {% id="08-07-2025" %} * `allow_adult` setting in Image to Video generation are now available in restricted regions.
See the [Veo](/docs/video?example=dialogue) page for details.
## July 31, 2025 {% id="07-31-2025" %} * Launched image-to-video generation for the Veo 3 Preview model.
* Released Veo 3 Fast Preview model.
* To learn more about Veo 3, visit the [Veo](/docs/video) page.
## July 22, 2025 {% id="07-22-2025" %} * Released `gemini-2.5-flash-lite`, our fast, low-cost, high-performance Gemini 2.5 model.
To learn more, see [Gemini 2.5 Flash-Lite](/docs/models#gemini-25-flash-lite).
## July 17, 2025 {% id="07-17-2025" %} * Launched `veo-3.0-generate-preview`, the latest update to Veo introducing video with audio generation.
To learn more about Veo 3, visit the [Veo](/docs/video) page.
* Increased rate limits for Imagen 4 Standard and Ultra.
Visit the [Rate limits](/docs/rate-limits) page for more details.
## July 14, 2025 {% id="07-14-2025" %} * Released `gemini-embedding-001`, the stable version of our text embedding model.
To learn more, see [embeddings](/docs/embeddings).
The `gemini-embedding-exp-03-07` model will be deprecated on August 14, 2025.
## July 7, 2025 {% id="07-07-2025" %} * Launched Gemini API Batch Mode.
Batch up requests and send them to process asynchronously.
To learn more, see [Batch Mode](/docs/batch-api).
## June 26, 2025 {% id="06-26-2025" %} * The preview models `gemini-2.5-pro-preview-05-06` and `gemini-2.5-pro-preview-03-25` are now redirecting to the latest stable version `gemini-2.5-pro`.
* `gemini-2.5-pro-exp-03-25` is shut down.
## June 24, 2025 {% id="06-24-2025" %} * Released Imagen 4 Ultra and Standard Preview models.
To learn more, see the [Image generation](/docs/image-generation) page.
## June 17, 2025 {% id="06-17-2025" %} * Released `gemini-2.5-pro`, the stable version of our most powerful model, now with adaptive thinking.
To learn more, see [Gemini 2.5 Pro](/docs/models#gemini-25-pro) and [Thinking](/docs/thinking).
`gemini-2.5-pro-preview-05-06` will be redirected to `gemini-2.5-pro` on June 26, 2025.
* Released `gemini-2.5-flash`, our first stable 2.5 Flash model.
To learn more, see [Gemini 2.5 Flash](/docs/models#gemini-25-flash).
`gemini-2.5-flash-preview-04-17` will be deprecated on July 15, 2025.
* Released `gemini-2.5-flash-lite-preview-06-17`, a low-cost, high-performance Gemini 2.5 model.
To learn more, see [Gemini 2.5 Flash-Lite Preview](/docs/models#gemini-25-flash-lite).
## June 05, 2025 {% id="06-05-2025" %} * Released `gemini-2.5-pro-preview-06-05`, a new version of our most powerful model, now with adaptive thinking.
To learn more, see [Gemini 2.5 Pro Preview](/docs/models) and [Thinking](/docs/thinking).
`gemini-2.5-pro-preview-05-06` will be redirected to `gemini-2.5-pro` on June 26, 2025.
## May 27, 2025 {% id="05-27-2025" %} * The last available tuning model, Gemini 1.5 Flash 001, has been shut down.
Tuning is no longer supported on any models.
See [Fine tuning with the Gemini API](/docs/model-tuning).
## May 20, 2025 {% id="05-20-2025" %} **API updates:** * Launched support for [custom video preprocessing](/docs/video-understanding#customize-video-processing) using clipping intervals and configurable frame rate sampling.
* Launched multi-tool use, which supports configuring [code execution](/docs/code-execution) and [Grounding with Google Search](/docs/google-search) on the same `generateContent` request.
* Launched support for [asynchronous function calls](/docs/live-api/tools#async-function-calling) in the Live API.
* Launched an experimental [URL context tool](/docs/url-context) for providing URLs as additional context to prompts.
**Model updates:** * Released `gemini-2.5-flash-preview-05-20`, a Gemini [preview](/docs/models#model-versions) model optimized for price-performance and adaptive thinking.
To learn more, see [Gemini 2.5 Flash Preview](/docs/models) and [Thinking](/docs/thinking).
* Released the [`gemini-2.5-pro-preview-tts`](/docs/models) and [`gemini-2.5-flash-preview-tts`](/docs/models) models, which are capable of [generating speech](/docs/speech-generation) with one or two speakers.
* Released the `lyria-realtime-exp` model, which [generates music](/docs/music-generation) in real time.
* Released `gemini-2.5-flash-preview-native-audio-dialog` and `gemini-2.5-flash-exp-native-audio-thinking-dialog`, new Gemini models for the Live API with native audio output capabilities.
To learn more, see the [Live API guide](/docs/live-api/capabilities#native-audio-output) and [Gemini 2.5 Flash Native Audio](/docs/models).
* Released `gemma-3n-e4b-it` preview, available on [AI Studio](https://aistudio.google.com) and through the Gemini API, as part of the [Gemma 3n](https://ai.google.dev/gemma/docs/3n) launch.
## May 7, 2025 {% id="05-07-2025" %} * Released `gemini-2.0-flash-preview-image-generation`, a preview model for generating and editing images.
To learn more, see [Image generation](https://ai.google.dev/docs/image-generation) and [Gemini 2.0 Flash Preview Image Generation](https://ai.google.dev/docs/models#gemini-2.0-flash-preview-image-generation).
## May 6, 2025 {% id="05-06-2025" %} * Released `gemini-2.5-pro-preview-05-06`, a new version of our most powerful model, with improvements on code and function calling.
`gemini-2.5-pro-preview-03-25` will automatically point to the new version of the model.
## April 17, 2025 {% id="04-17-2025" %} * Released `gemini-2.5-flash-preview-04-17`, a Gemini [preview](/docs/models#model-versions) model optimized for price-performance and adaptive thinking.
To learn more, see [Gemini 2.5 Flash Preview](/docs/models) and [Thinking](/docs/thinking).
## April 16, 2025 {% id="04-16-2025" %} * Launched context caching for [Gemini 2.0 Flash](/docs/models).
## April 9, 2025 {% id="04-09-2025" %} **Model updates:** * Released `veo-2.0-generate-001`, a generally available (GA) text- and image-to-video model, capable of generating detailed and artistically nuanced videos.
To learn more, see the [Veo docs](/docs/video).
* Released `gemini-2.0-flash-live-001`, a public preview version of the [Live API](/docs/live-api) model with billing enabled.
* **Enhanced Session Management and Reliability** * **Session Resumption:** Keep sessions alive across temporary network disruptions.
The API now supports server-side session state storage (for up to 24 hours) and provides handles (session_resumption) to reconnect and resume where you left off.
* **Longer Sessions via Context Compression:** Enable extended interactions beyond previous time limits.
Configure context window compression with a sliding window mechanism to automatically manage context length, preventing abrupt terminations due to context limits.
* **Graceful Disconnect Notification:** Receive a `GoAway` server message indicating when a connection is about to close, allowing for graceful handling before termination.
* **More Control over Interaction Dynamics** * **Configurable Voice Activity Detection (VAD):** Choose sensitivity levels or disable automatic VAD entirely and use new client events (`activityStart`, `activityEnd`) for manual turn control.
* **Configurable Interruption Handling:** Decide whether user input should interrupt the model's response.
* **Configurable Turn Coverage:** Choose whether the API processes all audio and video input continuously or only captures it when the end-user is detected speaking.
* **Configurable Media Resolution:** Optimize for quality or token usage by selecting the resolution for input media.
* **Richer Output and Features** * **Expanded Voice & Language Options:** Choose from two new voices and 30 new languages for audio output.
The output language is now configurable within `speechConfig`.
* **Text Streaming:** Receive text responses incrementally as they are generated, enabling faster display to the user.
* **Token Usage Reporting:** Gain insights into usage with detailed token counts provided in the `usageMetadata` field of server messages, broken down by modality and prompt or response phases.
## April 4, 2025 {% id="04-04-2025" %} * Released `gemini-2.5-pro-preview-03-25`, a public preview Gemini 2.5 Pro version with billing enabled.
You can continue to use `gemini-2.5-pro-exp-03-25` on sthe free tier.
## March 25, 2025 {% id="03-25-2025" %} * Released `gemini-2.5-pro-exp-03-25`, a public experimental Gemini model with thinking mode always on by default.
To learn more, see [Gemini 2.5 Pro Experimental](/docs/models).
## March 12, 2025 {% id="03-12-2025" %} **Model updates:** * Launched an experimental [Gemini 2.0 Flash](/docs/image-generation) model capable of image generation and editing.
* Released `gemma-3-27b-it`, available on [AI Studio](https://aistudio.google.com) and through the Gemini API, as part of the [Gemma 3](https://ai.google.dev/gemma/docs/core) launch.
**API updates:** * Added support for [YouTube URLs](/docs/image-understanding) as a media source.
* Added support for including an [inline video](/docs/image-understanding) of less than 20MB.
## March 11, 2025 {% id="03-11-2025" %} **SDK updates:** * Released the [Google Gen AI SDK for TypeScript and JavaScript](https://googleapis.github.io/js-genai) to public preview.
## March 7, 2025 {% id="03-07-2025" %} **Model updates:** * Released `gemini-embedding-exp-03-07`, an [experimental](/docs/models) Gemini-based embeddings model in public preview.
## February 28, 2025 {% id="02-28-2025" %} **API updates:** * Support for [Search as a tool](/docs/google-search) added to `gemini-2.0-pro-exp-02-05`, an experimental model based on Gemini 2.0 Pro.
## February 25, 2025 {% id="02-25-2025" %} **Model updates:** * Released `gemini-2.0-flash-lite`, a generally available (GA) version of [Gemini 2.0 Flash-Lite](/docs/models), which is optimized for speed, scale, and cost efficiency.
## February 19, 2025 {% id="02-19-2025" %} **AI Studio updates:** * Support for [additional regions](https://ai.google.dev/docs/available-regions) (Kosovo, Greenland and Faroe Islands).
**API updates:** * Support for [additional regions](https://ai.google.dev/docs/available-regions) (Kosovo, Greenland and Faroe Islands).
## February 18, 2025 {% id="02-18-2025" %} **Model updates:** * Gemini 1.0 Pro is no longer supported.
For the list of supported models, see [Gemini models](/docs/models).
## February 11, 2025 {% id="02-11-2025" %} **API updates:** * Updates on the [OpenAI libraries compatibility](https://ai.google.dev/docs/openai).
## February 6, 2025 {% id="02-06-2025" %} **Model updates:** * Released `imagen-3.0-generate-002`, a generally available (GA) version of [Imagen 3 in the Gemini API](/docs/image-generation).
**SDK updates:** * Released the [Google Gen AI SDK for Java](https://github.com/googleapis/java-genai) for public preview.
## February 5, 2025 {% id="02-05-2025" %} **Model updates:** * Released `gemini-2.0-flash-001`, a generally available (GA) version of [Gemini 2.0 Flash](/docs/models) that supports text-only output.
* Released `gemini-2.0-pro-exp-02-05`, an [experimental](/docs/models) public preview version of Gemini 2.0 Pro.
* Released `gemini-2.0-flash-lite-preview-02-05`, an experimental public preview [model](/docs/models) optimized for cost efficiency.
**API updates:** * Added [file input and graph output](/docs/code-execution#input-output) support to code execution.
**SDK updates:** * Released the [Google Gen AI SDK for Python](https://googleapis.github.io/python-genai/) to general availability (GA).
## January 21, 2025 {% id="01-21-2025" %} **Model updates:** * Released `gemini-2.0-flash-thinking-exp-01-21`, the latest preview version of the model behind the [Gemini 2.0 Flash Thinking Model](/docs/thinking).
## December 19, 2024 {% id="12-19-2024" %} **Model updates:** * Released Gemini 2.0 Flash Thinking Mode for public preview.
Thinking Mode is a test-time compute model that lets you see the model's thought process while it generates a response, and produces responses with stronger reasoning capabilities.
Read more about Gemini 2.0 Flash Thinking Mode in our [overview page](/docs/thinking).
## December 11, 2024 {% id="12-11-2024" %} **Model updates:** * Released [Gemini 2.0 Flash Experimental](/docs/models) for public preview.
Gemini 2.0 Flash Experimental's partial list of features includes: * Twice as fast as Gemini 1.5 Pro * Bidirectional streaming with our Live API * Multimodal response generation in the form of text, images, and speech * Built-in tool use with multi-turn reasoning to use features like code execution, Search, function calling, and more Read more about Gemini 2.0 Flash in our [overview page](/docs/models).
## November 21, 2024 {% id="11-21-24" %} **Model updates:** * Released `gemini-exp-1121`, an even more powerful experimental Gemini API model.
**Model updates:** * Updated the `gemini-1.5-flash-latest` and `gemini-1.5-flash` model aliases to use `gemini-1.5-flash-002`.
* Change to `top_k` parameter: The `gemini-1.5-flash-002` model supports `top_k` values between 1 and 41 (exclusive).
Values greater than 40 will be changed to 40.
## November 14, 2024 {% id="11-14-24" %} **Model updates:** * Released `gemini-exp-1114`, a powerful experimental Gemini API model.
## November 8, 2024 {% id="11-08-24" %} **API updates:** * Added [support for Gemini](/docs/openai) in the OpenAI libraries / REST API.
## October 31, 2024 {% id="10-31-24" %} **API updates:** * Added [support for Grounding with Google Search](/docs/google-search).
## October 3, 2024 {% id="10-03-24" %} **Model updates:** * Released `gemini-1.5-flash-8b-001`, a stable version of our smallest Gemini API model.
## September 24, 2024 {% id="09-24-24" %} **Model updates:** * Released `gemini-1.5-pro-002` and `gemini-1.5-flash-002`, two new stable versions of Gemini 1.5 Pro and 1.5 Flash, for general availability.
* Updated the `gemini-1.5-pro-latest` model code to use `gemini-1.5-pro-002` and the `gemini-1.5-flash-latest` model code to use `gemini-1.5-flash-002`.
* Released `gemini-1.5-flash-8b-exp-0924` to replace `gemini-1.5-flash-8b-exp-0827`.
* Released the [civic integrity safety filter](/docs/safety-settings#safety-filters) for the Gemini API and AI Studio.
* Released support for two new parameters for Gemini 1.5 Pro and 1.5 Flash in Python and NodeJS: [`frequencyPenalty`](https://ai.google.dev/api/generate-content#FIELDS.frequency_penalty) and [`presencePenalty`](https://ai.google.dev/api/generate-content#FIELDS.presence_penalty).
## September 19, 2024 {% id="09-19-24" %} **AI Studio updates:** * Added thumb-up and thumb-down buttons to model responses, to enable users to provide feedback on the quality of a response.
**API updates:** * Added support for Google Cloud credits, which can now be used towards Gemini API usage.
## September 17, 2024 {% id="09-17-24" %} **AI Studio updates:** * Added an **Open in Colab** button that exports a prompt – and the code to run it – to a Colab notebook.
The feature doesn't yet support prompting with tools (JSON mode, function calling, or code execution).
## September 13, 2024 {% id="09-13-24" %} **AI Studio updates:** * Added support for compare mode, which lets you compare responses across models and prompts to find the best fit for your use case.
## August 30, 2024 {% id="08-30-24" %} **Model updates:** * Gemini 1.5 Flash supports [supplying JSON schema through model configuration](/docs/structured-output).
## August 27, 2024 {% id="08-27-24" %} **Model updates:** * Released the following [experimental models](/docs/models): * `gemini-1.5-pro-exp-0827` * `gemini-1.5-flash-exp-0827` * `gemini-1.5-flash-8b-exp-0827` ## August 9, 2024 {% id="08-09-24" %} **API updates:** * Added support for [PDF processing](/docs/document-processing).
## August 5, 2024 {% id="08-05-24" %} **Model updates:** * Fine-tuning support released for Gemini 1.5 Flash.
## August 1, 2024 {% id="08-01-24" %} **Model updates:** * Released `gemini-1.5-pro-exp-0801`, a new experimental version of [Gemini 1.5 Pro](/docs/models).
## July 12, 2024 {% id="07-12-24" %} **Model updates:** * Support for Gemini 1.0 Pro Vision removed from Google AI services and tools.
## June 27, 2024 {% id="06-27-24" %} **Model updates:** * General availability release for Gemini 1.5 Pro's 2M context window.
**API updates:** * Added support for [code execution](/docs/code-execution).
## June 18, 2024 {% id="06-18-24" %} **API updates:** * Added support for [context caching](/docs/caching).
## June 12, 2024 {% id="06-12-204" %} **Model updates:** * Gemini 1.0 Pro Vision deprecated.
## May 23, 2024 {% id="05-23-24" %} **Model updates:** * [Gemini 1.5 Pro](/docs/models) (`gemini-1.5-pro-001`) is generally available (GA).
* [Gemini 1.5 Flash](/docs/models) (`gemini-1.5-flash-001`) is generally available (GA).
## May 14, 2024 {% id="05-14-24" %} **API updates:** * Introduced a 2M context window for Gemini 1.5 Pro (waitlist).
* Introduced pay-as-you-go [billing](/docs/billing) for Gemini 1.0 Pro, with Gemini 1.5 Pro and Gemini 1.5 Flash billing coming soon.
* Introduced increased rate limits for the upcoming paid tier of Gemini 1.5 Pro.
* Added built-in video support to the [File API](https://ai.google.dev/api/rest/v1beta/files).
* Added plain text support to the [File API](https://ai.google.dev/api/rest/v1beta/files).
* Added support for parallel function calling, which returns more than one call at a time.
## May 10, 2024 {% id="05-10-24" %} **Model updates:** * Released [Gemini 1.5 Flash](/docs/models) (`gemini-1.5-flash-latest`) in preview.
## April 9, 2024 {% id="04-09-24" %} **Model updates:** * Released [Gemini 1.5 Pro](/docs/models) (`gemini-1.5-pro-latest`) in preview.
* Released a new text embedding model, `text-embeddings-004`, which supports [elastic embedding](/docs/embeddings) sizes under 768.
**API updates:** * Released the [File API](https://ai.google.dev/api/rest/v1beta/files) for temporarily storing media files for use in prompting.
* Added support for prompting with text, image, and audio data, also known as *multimodal* prompting.
To learn more, see [Prompting with media](/docs/files#prompt-guide).
* Released [System instructions](/docs/text-generation) in beta.
* Added [Function calling mode](/docs/function-calling#function_calling_modes), which defines the execution behavior for function calling.
* Added support for the `response_mime_type` configuration option, which lets you request responses in [JSON format](https://ai.google.dev/api#json).
## March 19, 2024 {% id="03-09-24" %} **Model updates:** * Added support for [tuning Gemini 1.0 Pro](https://developers.googleblog.com/en/tune-gemini-pro-in-google-ai-studio-or-with-the-gemini-api/) in Google AI Studio or with the Gemini API.
## December 13 2023 {% id="12-13-23" %} **Model updates:** * gemini-pro: New text model for a wide variety of tasks.
Balances capability and efficiency.
* gemini-pro-vision: New multimodal model for a wide variety of tasks.
Balances capability and efficiency.
* embedding-001: New embeddings model.
* aqa: A new specially tuned model that is trained to answer questions using text passages for grounding generated answers.
See [Gemini models](/docs/models) for more details.
**API version updates:** * v1: The stable API channel.
* v1beta: Beta channel.
This channel has features that may be under development.
See [the API versions topic](https://ai.google.dev/gemini-api/docs/api-versions) for more details.
**API updates:** * `GenerateContent` is a single unified endpoint for chat and text.
* Streaming available through the `StreamGenerateContent` method.
* Multimodal capability: Image is a new supported modality * New beta features: * [Function Calling](/docs/function-calling) * Semantic Retriever * Attributed Question Answering (AQA) * Updated candidate count: Gemini models only return 1 candidate.
* Different Safety Settings and SafetyRating categories.
See [safety settings](/docs/safety-settings) for more details.
* Tuning models is not yet supported for Gemini models (Work in progress).
