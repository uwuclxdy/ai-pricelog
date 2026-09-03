> ## Documentation Index > Fetch the complete documentation index at: https://docs.z.ai/llms.txt > Use this file to discover all available pages before exploring further.
# Plan Update Announcement > This notice explains the plan update, how your current benefits are protected, and what happens to future subscriptions.
* Publication date: July 30, 2026 * All dates and times mentioned in this notice are in Singapore Standard Time (UTC+8).
To make usage clearer and easier to predict, GLM Coding Plan is moving to a credits-based system.
See the [Subscription](https://z.ai/subscribe) page and the usage guides for [Individual Plans](https://docs.z.ai/devpack/overview#usage-instruction) and [Team Plans](https://docs.z.ai/devpack/teamplan#usage-details) for new plan tiers, prices, credit amounts, and deduction rules.
<Tip> **Key points** * The new credits-based plan is now available.
Previous plans are no longer sold to new users.
* Existing active subscriptions are not affected.
In addition, usage on weekends will be deducted at off-peak rates all day.
* Users on plans discontinued on July 30 can still renew or upgrade them.
* Discontinued and new plans differ only in how usage is calculated.
Other benefits will remain aligned.
</Tip> ## Identify Your Current Plan Sign in and use the table below to identify your current plan and see how this update affects you.
| Plan type used in this notice | How to identify it | | :------------------------------------- | :---------------------------------------------------------------------------------------- | | Legacy Plan V1 (individual plans only) | [My plan](https://z.ai/manage-apikey/coding-plan/personal/my-plan) shows "Legacy Plan V1" | | Legacy Plan V2 (individual plans only) | [My plan](https://z.ai/manage-apikey/coding-plan/personal/my-plan) shows "Legacy Plan V2" | | Team Plan | [My Plan](https://z.ai/manage-apikey/coding-plan/team/plans) shows “Team Edition” | | No active plan | Your plan has expired,
or you have not subscribed | ## How This Update Affects You ### 1.
If you have a legacy plan V1 * Your current price, benefits, usage limits, and calculation method stay unchanged until the end of the current billing cycle.
* You cannot switch to the new credits-based plan before your current plan expires.
After it expires, you can subscribe to a currently available plan.
### 2.
If you have a legacy plan V2 * Your current price, benefits, usage limits, and calculation method stay unchanged until the end of the current billing cycle.
* While your plan is active, you can keep auto-renew enabled and upgrade your tier or billing term.
* You may switch immediately only when upgrading to a higher tier of the new credits-based plan.
For a same-tier switch or downgrade, wait until your current plan expires.
If you switch, your current plan ends immediately and its unused value is applied toward the new plan price.
### 3.
If you have a team plan * Your current price, benefits, usage limits, and calculation method stay unchanged until the end of the current billing cycle.
* You cannot switch to the new credits-based plan before your current plan expires.
After it expires, you can subscribe to a currently available plan.
### 4.
If you have no active plan or are subscribing for the first time * Starting July 30, 2026, you can subscribe directly to the new credits-based plan.
See the subscription page for current prices, credit amounts, and plan rules.
## FAQ **Q: Why is the usage calculation changing?** **A:** We want plan usage to be fully transparent.
The new credits-based plan is based on token usage, so credit deductions better reflect actual model usage.
You can also see how input, cached, and output tokens contribute to total usage and plan your usage more easily.
**Q: Will this update affect my current plan?** **A:** No.
If you subscribed before July 30, 2026, your active plan keeps its current price, benefits, usage limits, and calculation method until the end of the current billing cycle.
**Q: Can I renew or upgrade a legacy plan V2 discontinued on July 30?** **A:** Yes.
If you currently have a legacy plan V2, you can enable auto-renew or upgrade your plan.
**Q: When can I switch from a discontinued plan to a new plan?** **A:** It depends on your current plan: * **Legacy Plan V1**: You can subscribe to the new credits-based plan after your current plan expires.
* **Legacy Plan V2**: You can switch immediately when upgrading to a higher-tier new credits-based plan.
For a same-tier switch or downgrade, wait until your current plan expires.
Plans are not switched automatically.
You must subscribe or switch manually.
**Q: Can I still use the migration discount I received on April 30?** **A:** Yes.
If you met the eligibility requirements in the [Legacy Plan Migration Notice](/devpack/transition), your **50% Migration Support discount** remains valid through its original validity period and can be used for the new credits-based plan.
## Usage Reference for Legacy Plans ### Legacy Plan V2 To manage resources and ensure fair access for all users, we apply usage limits on a 5-hour and weekly basis.
You can check your quota consumption progress in [Usage Statistics](https://z.ai/manage-apikey/subscription).
One prompt refers to one query.
Each prompt is estimated to invoke the model 15–20 times.
**The monthly available quota is converted based on API pricing, equivalent to approximately 15–30× the monthly subscription fee (weekly caps already factored in).** | Plan Type | 5-Hour Limit (Dynamically refreshed; quota resets 5 hours after consumption) | Weekly Limit (Activated upon subscription; resets every 7 days) | | --------- | ---------------------------------------------------------------------------- | --------------------------------------------------------------- | | Lite Plan | Up to approx.
80 prompts | Up to approx.
400 prompts | | Pro Plan | Up to approx.
400 prompts | Up to approx.
2,000 prompts | | Max Plan | Up to approx.
1,600 prompts | Up to approx.
8,000 prompts | <Check> The above figures are estimates.
Actual available usage may vary depending on project complexity, repository size, and whether auto-accept is enabled.
<li> **GLM-5.3**: As the flagship model, API calls consume quota at a rate of "1× during off-peak hours and 3× during peak hours".
</li> <li> **GLM-5.3-Flash**: API calls consume quota at a rate of 0.4× during off-peak hours and 1.2× during peak hours.
</li> </Check> <Info> Peak hours: Monday to Friday, 14:00–18:00 Singapore Standard Time (UTC+8).
</Info> ### Team Plan <div style={{ overflowX: "auto" }}> <table style={{ width: "100%", minWidth: "700px", borderCollapse: "collapse", tableLayout: "fixed" }}> <thead> <tr> <th style={{ width: "140px", whiteSpace: "nowrap", textAlign: "center", padding: "12px", border: "1px solid #e5e7eb" }}> Plan Type </th> <th style={{ width: "calc((100% - 140px) / 2 - 5%)", textAlign: "center", padding: "12px", border: "1px solid #e5e7eb" }}> Quota per 5 hours / seat <br /> <span style={{ fontWeight: 600 }}> (Dynamically refreshed; quota is restored 5 hours after request consumption) </span> </th> <th
style={{ width: "calc((100% - 140px) / 2 + 5%)", textAlign: "center", padding: "12px", border: "1px solid #e5e7eb" }}> Weekly quota / seat <br /> <span style={{ fontWeight: 600 }}> (Starts at purchase; quota refreshes every 7-day cycle) </span> </th> </tr> </thead> <tbody> <tr> <td style={{ width: "140px", whiteSpace: "nowrap", textAlign: "center", padding: "12px", border: "1px solid #e5e7eb" }}> Standard Seat </td> <td style={{ textAlign: "left", padding: "12px", border: "1px solid #e5e7eb" }}> GLM-5.3: Up to 60 M tokens <br /> GLM-5.3-Flash: Up to 150 M tokens </td> <td style={{ textAlign:
"left", padding: "12px", border: "1px solid #e5e7eb" }}> GLM-5.3: Up to 300 M tokens <br /> GLM-5.3-Flash: Up to 750 M tokens </td> </tr> <tr> <td style={{ width: "140px", whiteSpace: "nowrap", textAlign: "center", padding: "12px", border: "1px solid #e5e7eb" }}> Premium Seat </td> <td style={{ textAlign: "left", padding: "12px", border: "1px solid #e5e7eb" }}> GLM-5.3: Up to 160 M tokens <br /> GLM-5.3-Flash: Up to 400 M tokens </td> <td style={{ textAlign: "left", padding: "12px", border: "1px solid #e5e7eb" }}> GLM-5.3: Up to 800 M tokens <br /> GLM-5.3-Flash: Up to 2,000 M tokens </td>
</tr> <tr> <td style={{ width: "140px", whiteSpace: "nowrap", textAlign: "center", padding: "12px", border: "1px solid #e5e7eb" }}> Notes </td> <td colSpan={2} style={{ padding: "16px", border: "1px solid #e5e7eb" }}> <p> “Maximum” refers to the total number of Tokens that can actually be consumed when the **off-peak consumption multiplier** applies.
</p> <p>The current quota consumption rules for each model are as follows:</p> <ul> <li> **GLM-5.3**: As the flagship model, API calls consume quota at a rate of "1× during off-peak hours and 3× during peak hours".
</li> <li> **GLM-5.3-Flash**: API calls consume quota at a rate of 0.4× during off-peak hours and 1.2× during peak hours.
</li> </ul> <p>\*Peak hours: Monday to Friday, 14:00–18:00 Singapore Standard Time (UTC+8).</p> </td> </tr> </tbody> </table> </div>
