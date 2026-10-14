import React from 'react';

/** Inline bold/italic/code rendering for one line of text (no dependencies). */
function inline(text, keyPrefix) {
  const parts = [];
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  let last = 0;
  let m;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const token = m[0];
    if (token.startsWith('**')) parts.push(<strong key={`${keyPrefix}-${i}`}>{token.slice(2, -2)}</strong>);
    else if (token.startsWith('*')) parts.push(<em key={`${keyPrefix}-${i}`}>{token.slice(1, -1)}</em>);
    else parts.push(<code key={`${keyPrefix}-${i}`}>{token.slice(1, -1)}</code>);
    i += 1;
    last = m.index + token.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts.length ? parts : [text];
}

/** Minimal block renderer: headings, bullets, numbered lists, paragraphs. */
export function Markdown({ text }) {
  if (!text) return null;
  const lines = text.split('\n');
  const blocks = [];
  let list = null;
  let ordered = null;

  const flush = () => {
    if (list) {
      blocks.push(
        <ul key={`ul-${blocks.length}`}>
          {list.map((item, i) => (
            <li key={i}>{inline(item, `ul-${blocks.length}-${i}`)}</li>
          ))}
        </ul>
      );
      list = null;
    }
    if (ordered) {
      blocks.push(
        <ol key={`ol-${blocks.length}`}>
          {ordered.map((item, i) => (
            <li key={i}>{inline(item, `ol-${blocks.length}-${i}`)}</li>
          ))}
        </ol>
      );
      ordered = null;
    }
  };

  lines.forEach((raw, idx) => {
    const line = raw.trim();
    if (!line) {
      flush();
      return;
    }
    const bullet = line.match(/^[-*•]\s+(.*)/);
    if (bullet) {
      if (ordered) flush();
      list = list || [];
      list.push(bullet[1]);
      return;
    }
    const num = line.match(/^\d+[.)]\s+(.*)/);
    if (num) {
      if (list) flush();
      ordered = ordered || [];
      ordered.push(num[1]);
      return;
    }
    flush();
    const heading = line.match(/^(#{1,3})\s+(.*)/);
    if (heading) {
      const level = heading[1].length;
      const Tag = level === 1 ? 'h3' : level === 2 ? 'h4' : 'h5';
      blocks.push(<Tag key={idx}>{inline(heading[2], `h-${idx}`)}</Tag>);
      return;
    }
    if (line === '---' || line === '***') {
      blocks.push(<hr key={idx} />);
      return;
    }
    blocks.push(<p key={idx}>{inline(line, `p-${idx}`)}</p>);
  });
  flush();
  return <>{blocks}</>;
}
