> ## Documentation Index
> Fetch the complete documentation index at: https://platform.kimi.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Model List

> Review currently available Kimi multimodal, coding, and Moonshot V1 models, plus migration guidance for discontinued models.

Click [here](pricing/chat) to see more details of model price.

<Note>
  Following the Kimi K3 launch, `kimi-k2.5` and the `moonshot-v1` series are no longer available to newly registered users (full platform sunset on August 31). Please switch to a newer model as soon as possible.
</Note>

## Multi-modal Model

| Model Name                 | Description                                                                                                                                                                                                                                 |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `kimi-k3`                  | Kimi's most capable model to date, with 2.8 trillion parameters, native visual understanding, and a 1M-token context window, designed for frontier intelligence scenarios such as software engineering, knowledge work, and deep reasoning. |
| `kimi-k2.7-code`           | Kimi's dedicated coding model. It follows instructions more reliably in long contexts, completes coding tasks with higher success rates. Context 256k                                                                                       |
| `kimi-k2.7-code-highspeed` | High-Speed version of Kimi K2.7 Code model, with output speed of approximately 180 Tokens/s and up to 260 Tokens/s in short context scenarios, delivering a more extreme coding experience.                                                 |
| `kimi-k2.6`                | Supports both visual and text input, thinking and non-thinking modes, and dialogue and Agent tasks. Context 256k                                                                                                                            |
| `kimi-k2.5`                | Achieves open-source SoTA performance in Agent, code, visual understanding, and a range of general intelligent tasks. It also supports visual and text input, thinking and non-thinking modes, and dialogue and Agent tasks. Context 256k   |

## Generation Model Moonshot V1

| Model Name                        | Description                                                                   |
| --------------------------------- | ----------------------------------------------------------------------------- |
| `moonshot-v1-8k`                  | Suitable for generating short texts, context length 8k                        |
| `moonshot-v1-32k`                 | Suitable for generating long texts, context length 32k                        |
| `moonshot-v1-128k`                | Suitable for generating very long texts, context length 128k                  |
| `moonshot-v1-8k-vision-preview`   | Vision model, understands image content and outputs text, context length 8k   |
| `moonshot-v1-32k-vision-preview`  | Vision model, understands image content and outputs text, context length 32k  |
| `moonshot-v1-128k-vision-preview` | Vision model, understands image content and outputs text, context length 128k |

> Note: The only difference between these Moonshot V1 models is their maximum context length (including input and output), there is no difference in effect.

## Deprecated Models

> The `kimi-k2` series models were officially discontinued on **May 25, 2026** and are no longer maintained or supported. Please use the latest Kimi model [kimi-k3](/docs/guide/kimi-k3-quickstart) for continued support and enhanced reasoning capabilities.

| Model Name               | Description |
| ------------------------ | ----------- |
| `kimi-k2-0905-preview`   | Deprecated  |
| `kimi-k2-0711-preview`   | Deprecated  |
| `kimi-k2-turbo-preview`  | Deprecated  |
| `kimi-k2-thinking`       | Deprecated  |
| `kimi-k2-thinking-turbo` | Deprecated  |

> `kimi-latest` was officially discontinued on **January 28, 2026** and is no longer maintained or supported. Please use the latest Kimi model [kimi-k3](/docs/guide/kimi-k3-quickstart) for continued support and enhanced reasoning capabilities.

> `kimi-thinking-preview` was officially discontinued on **November 11, 2025** and is no longer maintained or supported. We recommend upgrading to the latest model [kimi-k3](/docs/guide/kimi-k3-quickstart) for continued support and enhanced reasoning capabilities.

For further assistance, please [contact sales](https://platform.kimi.ai/contact-sales).
