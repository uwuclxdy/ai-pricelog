> ## Documentation Index
> Fetch the complete documentation index at: https://platform.minimax.io/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Pay as You Go

> MiniMax Pay as You Go Pricing

Pay-as-you-go uses standard Open Platform API Keys and consumes your account balance by actual usage. Credits are a separate prepaid balance used through a Subscription Key with the same resource coverage as Token Plan. For Credits pricing and usage behavior, see [Token Plan pricing](/docs/guides/pricing-token-plan).

## LLM

[Recharge Now](https://platform.minimax.io/user-center/payment/balance)

<Tabs>
  <Tab title="Standard">
    | Model                                                                                                                                                                                                                    | Input                        | Output                       | Prompt caching Read          |
    | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :--------------------------- | :--------------------------- | :--------------------------- |
    | **MiniMax-M3**<br />≤ 512k input tokens <span className="inline-flex items-center rounded-full bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-700 dark:bg-red-900/30 dark:text-red-300">Permanent 50% off</span>   | ~~\$0.60~~ \$0.30 / M tokens | ~~\$2.40~~ \$1.20 / M tokens | ~~\$0.12~~ \$0.06 / M tokens |
    | **MiniMax-M3**<br />> 512k input tokens\* <span className="inline-flex items-center rounded-full bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-700 dark:bg-red-900/30 dark:text-red-300">Permanent 50% off</span> | ~~\$1.20~~ \$0.60 / M tokens | ~~\$4.80~~ \$2.40 / M tokens | ~~\$0.24~~ \$0.12 / M tokens |
  </Tab>

  <Tab title="Priority*">
    | Model                                                                                                                                                                                                                  | Input                        | Output                       | Prompt caching Read          |
    | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :--------------------------- | :--------------------------- | :--------------------------- |
    | **MiniMax-M3**<br />≤ 512k input tokens <span className="inline-flex items-center rounded-full bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-700 dark:bg-red-900/30 dark:text-red-300">Permanent 50% off</span> | ~~\$0.90~~ \$0.45 / M tokens | ~~\$3.60~~ \$1.80 / M tokens | ~~\$0.18~~ \$0.09 / M tokens |
    | **MiniMax-M3**<br />> 512k input tokens <span className="inline-flex items-center rounded-full bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-700 dark:bg-red-900/30 dark:text-red-300">Permanent 50% off</span> | ~~\$1.80~~ \$0.90 / M tokens | ~~\$7.20~~ \$3.60 / M tokens | ~~\$0.36~~ \$0.18 / M tokens |

    \* Priority provides priority admission for faster response times and improved request reliability. Set `service_tier` to `priority` to enable it. Pricing is 1.5x standard.
  </Tab>
</Tabs>

| Model                      | Input            | Output           | Prompt caching Read | Prompt caching Write |
| :------------------------- | :--------------- | :--------------- | :------------------ | :------------------- |
| **MiniMax-M2.7**           | \$0.3 / M tokens | \$1.2 / M tokens | \$0.06 / M tokens   | \$0.375 / M tokens   |
| **MiniMax-M2.7-highspeed** | \$0.6 / M tokens | \$2.4 / M tokens | \$0.06 / M tokens   | \$0.375 / M tokens   |

<Accordion title="Legacy Models">
  | Model                      | Input            | Output           | Prompt caching Read | Prompt caching Write |
  | :------------------------- | :--------------- | :--------------- | :------------------ | :------------------- |
  | **MiniMax-M2.5**           | \$0.3 / M tokens | \$1.2 / M tokens | \$0.03 / M tokens   | \$0.375 / M tokens   |
  | **MiniMax-M2.5-highspeed** | \$0.6 / M tokens | \$2.4 / M tokens | \$0.03 / M tokens   | \$0.375 / M tokens   |
  | **MiniMax-M2.1**           | \$0.3 / M tokens | \$1.2 / M tokens | \$0.03 / M tokens   | \$0.375 / M tokens   |
  | **MiniMax-M2.1-highspeed** | \$0.6 / M tokens | \$2.4 / M tokens | \$0.03 / M tokens   | \$0.375 / M tokens   |
  | **MiniMax-M2**             | \$0.3 / M tokens | \$1.2 / M tokens | \$0.03 / M tokens   | \$0.375 / M tokens   |
</Accordion>

<Info>
  Note:

  1. The billing item is token count; the token-to-character ratio varies slightly depending on the usage scenario, subject to actual consumption
  2. Token to English word ratio (estimate): approximately 750 English words consume 1000 tokens
</Info>

## Audio

[Recharge Now](https://platform.minimax.io/user-center/payment/balance)

| API                     | Model            | Price              |
| :---------------------- | :--------------- | :----------------- |
| **T2A**                 | speech-2.8-turbo | \$60/M characters  |
| **T2A**                 | speech-2.8-hd    | \$100/M characters |
| **Rapid Voice Cloning** | All Models       | \$1.5 per voice    |
| **Voice Design**        | All Models       | \$3 per voice      |

<Accordion title="Legacy Models">
  | API     | Model                              | Price              |
  | :------ | :--------------------------------- | :----------------- |
  | **T2A** | speech-2.6-turbo / speech-02-turbo | \$60/M characters  |
  | **T2A** | speech-2.6-hd / speech-02-hd       | \$100/M characters |
</Accordion>

## Video

[Recharge Now](https://platform.minimax.io/user-center/payment/balance)

**Video Generation - Output Pricing**

| **Model / API**                                  | **Resolution** | **Billing Rules** | **List Price**  |
| :----------------------------------------------- | :------------- | :---------------- | :-------------- |
| <div style={{minWidth:'240px'}}>MiniMax-H3</div> | 2K             | Billed per second | \$0.13 / second |
| <div style={{minWidth:'240px'}}>MiniMax-H3</div> | 768P           | Billed per second | \$0.08 / second |

**Video Generation - Input Material Pricing**

| **Model / API**                                  | **Material Type** | **Billing Rules**                                                                                  |
| :----------------------------------------------- | :---------------- | :------------------------------------------------------------------------------------------------- |
| <div style={{minWidth:'240px'}}>MiniMax-H3</div> | Audio             | Free                                                                                               |
| <div style={{minWidth:'240px'}}>MiniMax-H3</div> | Image             | First **5 images** free; **\$0.04 per additional image**                                           |
| <div style={{minWidth:'240px'}}>MiniMax-H3</div> | Video             | Billed by input video duration and output video resolution: **2K \$0.13/sec**, **768P \$0.08/sec** |

**Video Regeneration - Output Pricing**

Regenerate a previously produced 768P video into 2K, billed per second of the regenerated output.

| **Model / API**                                               | **Resolution** | **Billing Rules**                           | **List Price**  |
| :------------------------------------------------------------ | :------------- | :------------------------------------------ | :-------------- |
| <div style={{minWidth:'240px'}}>MiniMax-H3-Regeneration</div> | 768P → 2K      | Billed per second of the regenerated output | \$0.05 / second |

**Video Regeneration - Input Material Pricing**

The input materials used in the original 768P generation task will be billed again.

| **Model / API**                                               | **Material Type** | **Billing Rules**                                                               |
| :------------------------------------------------------------ | :---------------- | :------------------------------------------------------------------------------ |
| <div style={{minWidth:'240px'}}>MiniMax-H3-Regeneration</div> | Audio             | Free                                                                            |
| <div style={{minWidth:'240px'}}>MiniMax-H3-Regeneration</div> | Image             | First **5 images** free; **\$0.025 per additional image**                       |
| <div style={{minWidth:'240px'}}>MiniMax-H3-Regeneration</div> | Video             | Billed by input video duration from the original 768P task: **\$0.05 / second** |

**H3-Context-IR Task Pricing**

| **Model / API**                                             |  **Input Price**  |  **Output Price** |
| :---------------------------------------------------------- | :---------------: | :---------------: |
| <div style={{minWidth:'240px'}}>MiniMax-H3-Context-IR</div> | \$0.90 / M tokens | \$3.60 / M tokens |

<Accordion title="Legacy Models">
  | Model                   | Price                      |
  | :---------------------- | :------------------------- |
  | MiniMax-Hailuo-2.3-Fast | \$0.19 per 768P, 6s video  |
  | MiniMax-Hailuo-2.3-Fast | \$0.32 per 768P, 10s video |
  | MiniMax-Hailuo-2.3-Fast | \$0.33 per 1080P, 6s video |
  | MiniMax-Hailuo-2.3      | \$0.28 per 768P, 6s video  |
  | MiniMax-Hailuo-2.3      | \$0.56 per 768P, 10s video |
  | MiniMax-Hailuo-2.3      | \$0.49 per 1080P, 6s video |
  | MiniMax-Hailuo-02       | \$0.28 per 768P, 6s video  |
  | MiniMax-Hailuo-02       | \$0.56 per 768P, 10s video |
  | MiniMax-Hailuo-02       | \$0.49 per 1080P, 6s video |
  | MiniMax-Hailuo-02       | \$0.10 per 512P, 6s video  |
  | MiniMax-Hailuo-02       | \$0.15 per 512P, 10s video |
</Accordion>

## Music

[Recharge Now](https://platform.minimax.io/user-center/payment/balance)

| Model             | Description                          |             Price            |
| :---------------- | :----------------------------------- | :--------------------------: |
| Music-3.0-free    | RPM = 3                              |             Free             |
| Music-3.0         | RPM = 120, contact sales to increase | \$0.15/up-to-5 minutes music |
| Music-2.6-free    | RPM = 3                              |             Free             |
| Music-2.6         | RPM = 120, contact sales to increase | \$0.15/up-to-5 minutes music |
| Lyrics Generation | Lyrics generation/editing            |        \$0.01/per song       |

<Accordion title="Legacy Models">
  | Model      | Description                                           |             Price            |
  | :--------- | :---------------------------------------------------- | :--------------------------: |
  | Music-2.5+ | Instrumental unlocked, break through style boundaries | \$0.15/up-to-5 minutes music |
  | Music-2.5  | Direct the detail, define the real                    | \$0.15/up-to-5 minutes music |
  | Music-2.0  | Enhanced musical expression                           | \$0.03/up-to-5 minutes music |
</Accordion>

## Image

[Recharge Now](https://platform.minimax.io/user-center/payment/balance)

| Model    | Price              |
| :------- | :----------------- |
| image-01 | \$0.0035 per image |

## MCP

[Recharge Now](https://platform.minimax.io/user-center/payment/balance)

| Model       | Input Price      |
| :---------- | :--------------- |
| **API-vlm** | \$0.01 / request |

When API-vlm is called through Token Plan, usage deducts from the included Token Plan quota according to its pay-as-you-go price. If the included quota is exhausted and purchased Credits are available, additional usage can be automatically covered by purchased Credits.

<Callout color="#FFC107">
  🔔 **Pricing Update Notice** — Effective July 22, 2026, the API-vlm price will be adjusted to \$0.01 per call. Accordingly, the token quota deducted per API-vlm call under Token Plan subscriptions will decrease, allowing the same plan to support more calls. API endpoints and model capabilities remain unchanged — no code changes required.
</Callout>

## Server Tools <span className="inline-flex items-center rounded-full bg-blue-50 px-2 py-0.5 text-xs font-semibold text-blue-700 before:content-['Beta'] dark:bg-blue-900/30 dark:text-blue-300" />

[Recharge Now](https://platform.minimax.io/user-center/payment/balance)

| Server Tool     | Description                                                                                                                     | Price            |
| :-------------- | :------------------------------------------------------------------------------------------------------------------------------ | :--------------- |
| **web\_search** | Web search; the model runs the search on the server and answers based on the results. See [Server Tools](/docs/guides/server-tools). | \$0.01 / request |
