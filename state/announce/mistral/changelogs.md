Changelog | Mistral Docs Docs & API Search docs ⌘K Vibe Studio Inference & Models Admin Resources API Reference Search docs ⌘K Toggle theme Reach out Try Studio Home Resources Build API Reference SDKs MCP Supported languages Cookbooks Migration guides Updates Release notes Changelogs Security advisories Knowledge base Glossary Error glossary Known limitations Observability integrations Deprecated features Community Ambassadors Mistral Events ↗ Resources Changelogs Changelog Find out about all the latest changes to our tool.
You may filter by date and type of release.
Aug 26 August 31 OCR 4.1 ( mistral-ocr-4-1 ) is now Generally Available.
MODEL RELEASED Jul 26 July 16 We released OCR 4.1 ( mistral-ocr-4-1 ).
mistral-ocr-latest and mistral-ocr-4 now point to it.
MODEL RELEASED The OCR API confidence_scores_granularity parameter now supports "block" granularity.
"page" returns page-level scores only, "block" returns page-level and block-level scores, and "word" returns page-level and word-level scores.
API UPDATED Jun 26 June 30 We released Leanstral 1.5 ( labs-leanstral-1-5 ), an updated Lean 4 formal proof engineering model with improved SFT mixture quality and extended long-context reasoning.
This model will be retired on September 30, 2026 .
MODEL RELEASED June 23 We released OCR 4 ( mistral-ocr-4-0 ).
mistral-ocr-latest now points to it.
MODEL RELEASED Introducing include_blocks in our OCR API.
When set to true , each page returns a blocks array with paragraph-level bounding boxes and a structural label ( text , title , list , table , image , equation , caption , code , references , aside_text , header , footer , signature ) in reading order.
Learn more in our OCR documentation .
API UPDATED The pages parameter in our OCR API now also accepts a string of comma-separated digits and ranges (e.g.
"0,1,2" , "0-5" , or "0,2-4" ) in addition to a list of integers.
API UPDATED May 26 May 28 We launched Vibe , our unified agent at chat.mistral.ai , available in three modes: OTHER Work for productivity on web and mobile, with Skills, Workflows, Connectors, Libraries, and scheduled tasks.
Code for developers, covering the Vibe CLI , the VS Code extension , and Vibe Code Web for remote coding sessions in a managed cloud sandbox.
Chat preserves the legacy Le Chat experience for existing workflows.
Documentation restructured: previous /le-chat/* and /mistral-vibe/* paths now redirect to the new /vibe/* tree.
OTHER Apr 26 April 28 We released Mistral Medium 3.5 ( mistral-medium-3-5 ), our frontier-class multimodal model optimized for agentic and coding use cases, with adjustable reasoning via the reasoning_effort parameter.
Released as open weights under a Modified MIT license.
MODEL RELEASED Mar 26 March 23 We released Voxtral TTS ( voxtral-tts-2603 ), our state-of-the-art text-to-speech model with zero-shot voice cloning, multilingual support, and real-time streaming.
MODEL RELEASED March 16 We released Mistral Small 4 ( mistral-small-2603 ), a hybrid model unifying instruct, reasoning, and coding in a single multimodal model with a 256k context window.
MODEL RELEASED We released Leanstral ( labs-leanstral-2603 ), our first open-source code agent designed for Lean 4 formal proof engineering.
MODEL RELEASED March 12 We released Mistral Moderation 2603 ( mistral-moderation-2603 ).
MODEL RELEASED We added Custom Guardrails support for Agents and Conversations.
API UPDATED Guardrails can now be configured directly on an Agent via the guardrails parameter.
Guardrails can be passed per-request on POST /v1/conversations using the guardrails field.
Guardrails can be passed per-request on POST /v1/chat/completions using the guardrails field.
Feb 26 February 4 We released Voxtral Mini Transcribe 2 ( voxtral-mini-2602 ) and Voxtral Mini Transcribe Realtime ( voxtral-mini-transcribe-realtime-2602 ).
MODEL RELEASED Introducing context biasing in our Audio Transcriptions API, Introducing diarize in our Audio Transcriptions API.
Jan 26 January 27 We released Vibe 2.0.
OTHER Devstral 2.0 moves to paid API access.
MODEL RELEASED Document Annotations update and improvements, 8 page limit removed.
API UPDATED January 19 We released inline batching allowing the creation of batch jobs without file uploading.
API UPDATED Dec 25 December 18 We released OCR 3 ( mistral-ocr-2512 ).
MODEL RELEASED Introducing table_format in our OCR API, allowing you to choose between markdown and html for table formatting.
API UPDATED Introducing extract_footer , extract_header in our OCR API, as well as hyperlinks output.
API UPDATED December 16 We released Mistral Small Creative ( labs-mistral-small-creative ) as a Labs model.
MODEL RELEASED December 9 We released Devstral 2 ( devstral-2512 ) and Devstral Small 2 ( labs-devstral-small-2512 ).
MODEL RELEASED We released Mistral Vibe.
OTHER December 2 We released Mistral Large 3 ( mistral-large-2512 ) and Ministral 3 ( ministral-3b-2512 , ministral-8b-2512 and ministral-14b-2512 ).
MODEL RELEASED Sep 25 September 17 We released Magistral Medium 1.2 ( magistral-medium-2509 ) and Magistral Small 1.2 ( magistral-small-2509 ).
MODEL RELEASED Aug 25 August 27 Added a new parameter p to the chunks streamed back by the Completion API.
SECURITY API UPDATED Implemented for security to prevent token-length side-channel attacks, as reported by Microsoft researchers.
Note that this change may break applications relying on strict parsing of the chunks.
Applications using the official SDK are unaffected, but users relying on the mistral-common package may need to update to 1.8.4 or higher.
August 12 We released Mistral Medium 3.1 (mistral-medium-2508).
MODEL RELEASED Jul 25 July 30 We released Codestral 2508 ( codestral-2508 ).
MODEL RELEASED July 24 We released Magistral Medium 1.1 ( magistral-medium-2507 ) and Magistral Small 1.1 ( magistral-small-2507 ).
MODEL RELEASED We released a Document Library API to manage libraries.
API UPDATED SDK support for Audio and Transcription available.
OTHER July 15 We released our first Audio models for chat and a Transcription API: Voxtral Small ( voxtral-small-2507 ) available for chat use cases MODEL RELEASED Voxtral Mini ( voxtral-mini-2507 ) available for chat use cases MODEL RELEASED Voxtral Mini Transcribe ( voxtral-mini-2507 via audio/transcriptions ) optimized for transcription MODEL RELEASED API UPDATED July 10 We released Devstral Small 1.1 ( devstral-small-2507 ) and Devstral Medium ( devstral-medium-2507 ).
MODEL RELEASED Jun 25 June 23 Mistral Small 3.2 API available ( mistral-small-2506 ).
API UPDATED June 20 We released Mistral Small 3.2.
MODEL RELEASED June 10 We released Magistral Medium ( magistral-medium-2506 ) and Magistral Small ( magistral-small-2506 ).
MODEL RELEASED May 25 May 28 We released Codestral Embed ( codestral-embed ).
MODEL RELEASED May 27 We released the new Agents API .
API UPDATED May 22 We released Mistral OCR 2 ( mistral-ocr-2505 ) and annotations .
MODEL RELEASED API UPDATED May 21 We released Devstral Small ( devstral-small-2505 ).
MODEL RELEASED May 7 We released Mistral Medium 3 ( mistral-medium-2505 ).
MODEL RELEASED Apr 25 April 16 We released the Classifier Factory .
API UPDATED Mar 25 March 17 We released Mistral Small 3.1 ( mistral-small-2503 ).
MODEL RELEASED March 6 We released Mistral OCR ( mistral-ocr-2503 ) and document understanding .
MODEL RELEASED API UPDATED Feb 25 February 17 We released Mistral Saba ( mistral-saba-2502 ).
MODEL RELEASED Jan 25 January 30 We released Mistral Small 3 ( mistral-small-2501 ).
MODEL RELEASED January 28 We released custom structured outputs for all models.
API UPDATED January 13 We released Codestral 2501 ( codestral-2501 ).
MODEL RELEASED Nov 24 November 18 We released Mistral Large 2.1 ( mistral-large-2411 ) and Pixtral Large ( pixtral-large-2411 ).
MODEL RELEASED Le Chat : OTHER Web search with citations Canvas for ideation, in-line editing, and export State of the art document and image understanding, powered by the new multimodal Pixtral Large Image generation, powered by Black Forest Labs Flux Pro Fully integrated offering, from models to outputs Faster responses powered by speculative editing November 6 We released moderation API and batch API.
MODEL RELEASED API UPDATED We introduced three new parameters: API UPDATED presence_penalty : penalizes the repetition of words or phrases frequency_penalty : penalizes the repetition of words based on their frequency in the generated text n : number of completions to return for each request, input tokens are only billed once.
We downscaled the temperature parameter of pixtral-12b , ministral-3b-2410 , and ministral-8b-2410 by a multiplier of 0.43 to improve consistency, quality, and unify model behavior.
API UPDATED Oct 24 October 9 We released Ministral 3B ( ministral-3b-2410 ) and Ministral 8B ( ministral-8b-2410 ).
MODEL RELEASED Sep 24 September 17 We released Pixtral ( pixtral-12b-2409 ) and Mistral Small v24.09 ( mistral-small-2409 ).
MODEL RELEASED We reduced price on our flagship model, Mistral Large 2.
API UPDATED We introduced a free API tier on La Plateforme.
API UPDATED September 13 In le Chat, we added a mitigation against an obfuscated prompt method that could lead to data exfiltration, reported by researchers Xiaohan Fu and Earlence Fernandes.
The attack required users to willingfully copy and paste adversarial prompts and provide personal data to the model.
No user was impacted and no data was exfiltrated.
SECURITY Jul 24 July 29 We released version 1.0 of our Python and JS SDKs with major upgrades and syntax changes.
Check out our migration guide for details.
OTHER We released Agents API.
See details here .
API UPDATED July 24 We released Mistral Large 2 ( mistral-large-2407 ).
MODEL RELEASED We added fine-tuning support for Codestral, Mistral Nemo and Mistral Large.
Now the model choices for fine-tuning are open-mistral-7b (v0.3), mistral-small-latest ( mistral-small-2402 ), codestral-latest ( codestral-2405 ), open-mistral-nemo and , mistral-large-latest ( mistral-large-2407 ) API UPDATED July 18 We released Mistral Nemo ( open-mistral-nemo ).
MODEL RELEASED July 16 We released Codestral Mamba ( open-codestral-mamba ) and Mathstral.
MODEL RELEASED Jun 24 June 5 We released fine-tuning API.
Check out the capability docs and guides .
API UPDATED May 24 May 29 New model available: codestral-latest (aka codestral-2405 ).
Check out the code generation docs .
MODEL RELEASED API UPDATED May 23 Function calling: tool_call_id is now mandatory in chat messages with the tool role.
API UPDATED Apr 24 April 17 New model available: open-mixtral-8x22b (aka open-mixtral-8x22b-2404 ).
Check the release blog for details.
MODEL RELEASED For function calling, tool_call_id must not be null for open-mixtral-8x22b .
OTHER We released three versions of tokenizers for commercial and open-weight models: check the related guide and repo for more details.
OTHER Mar 24 March 28 JSON mode now available for all models on La Plateforme.
API UPDATED Feb 24 February 26 API endpoints: We renamed 3 API endpoints and added 2 model endpoints.
API UPDATED open-mistral-7b (aka mistral-tiny-2312 ): renamed from mistral-tiny .
The endpoint mistral-tiny will be deprecated in three months.
open-mixtral-8x7B (aka mistral-small-2312 ): renamed from mistral-small .
The endpoint mistral-small will be deprecated in three months.
mistral-small-latest (aka mistral-small-2402 ): new model.
MODEL RELEASED mistral-medium-latest (aka mistral-medium-2312 ): old model.
The previous mistral-medium has been dated and tagged as mistral-medium-2312 .
The endpoint mistral-medium will be deprecated in three months.
mistral-large-latest (aka mistral-large-2402 ): our new flagship model with leading performance.
MODEL RELEASED New API capabilities: API UPDATED Function calling : available for Mistral Small and Mistral Large.
JSON mode : available for Mistral Small and Mistral Large La Plateforme : OTHER We added multiple currency support to the payment system, including the option to pay in US dollars.
We introduced enterprise platform features including admin management, which allows users to manage individuals from your organization.
Le Chat : OTHER We introduced the brand new chat interface Le Chat to easily interact with Mistral models.
You can currently interact with three models: Mistral Large, Mistral Next, and Mistral Small.
Jan 24 January 16 We added token usage information in streaming requests.
You can find it in the last chunk returned.
API UPDATED January 11 We have enhanced the API's strictness.
Previously the API would silently ignores unsupported parameters in the requests, but it now strictly enforces the validity of all parameters.
If you have unsupported parameters in your request, you will see the error message "Extra inputs are not permitted".
API UPDATED A previous version of the guardrailing documentation incorrectly referred to the API parameter as safe_mode instead of safe_prompt .
We corrected this in the documentation.
OTHER WHY MISTRAL About us Our customers Careers Contact us EXPLORE AI Solutions Partners Research DOCUMENTATION Documentation Ambassadors Cookbooks BUILD Studio Vibe Mistral Code Mistral Compute Try the API LEGAL Terms of service Privacy policy Legal notice Privacy Choices Brand COMMUNITY Discord ↗ X ↗ Github ↗ LinkedIn ↗ Ambassadors Mistral AI © 2026 Toggle theme YEAR TAG Supported languages Cookbooks YEAR 2026 August July June May April March February January 2025 December September August July June May April March February January 2024 November October September July June May April March
February January Filters Clear model api other security Go to Top
