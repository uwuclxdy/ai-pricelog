> ## Documentation Index
> Fetch the complete documentation index at: https://platform.kimi.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Generation Model Moonshot V1 Pricing

> Review Moonshot V1 generation and vision model pricing for input, output, and cache-hit tokens, along with billing notes.

export const DocTable = ({columns = [], rows = []}) => {
  return <div className="doc-table-wrap">
      <table className="doc-table">
        {columns.length > 0 ? <colgroup>
            {columns.map((column, index) => <col key={index} style={column.width ? {
    width: column.width
  } : undefined} />)}
          </colgroup> : null}
        <thead>
          <tr>
            {columns.map((column, index) => <th key={index}>{column.title}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => <tr key={rowIndex}>
              {row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}
            </tr>)}
        </tbody>
      </table>
    </div>;
};

## Product Pricing

**Explanation: Prices exclude applicable taxes. Specific tax obligations are subject to local tax regulations and will be calculated at checkout based on your jurisdiction.**

<DocTable
  columns={[
{ title: "Model", width: "34%" },
{ title: "Unit", width: "14%" },
{ title: "Input Price", width: "14%" },
{ title: "Output Price", width: "14%" },
{ title: "Context Window", width: "24%" },
]}
  rows={[
["moonshot-v1-8k", "1M tokens", <>{"$"}0.20</>, <>{"$"}2.00</>, "8,192 tokens"],
["moonshot-v1-32k", "1M tokens", <>{"$"}1.00</>, <>{"$"}3.00</>, "32,768 tokens"],
["moonshot-v1-128k", "1M tokens", <>{"$"}2.00</>, <>{"$"}5.00</>, "131,072 tokens"],
["moonshot-v1-8k-vision-preview", "1M tokens", <>{"$"}0.20</>, <>{"$"}2.00</>, "8,192 tokens"],
["moonshot-v1-32k-vision-preview", "1M tokens", <>{"$"}1.00</>, <>{"$"}3.00</>, "32,768 tokens"],
["moonshot-v1-128k-vision-preview", "1M tokens", <>{"$"}2.00</>, <>{"$"}5.00</>, "131,072 tokens"],
]}
/>

Here, 1M = 1,000,000. The prices in the table represent the cost per 1M tokens consumed.
