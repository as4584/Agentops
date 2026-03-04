1. TypeScript interface
```ts
import { CSSProperties } from 'react';
// no Mantine or @tabler/icons-react imports required — all styling via CSS modules
interface Pillar {
  step: '01' | '02' | '03' | '04';
  title: string;
  description: string;
}
```

2. Component structure
```tsx
// app/components/LifecycleSection/LifecycleSection.tsx
import styles from './LifecycleSection.module.css';
const pillars: Pillar[] = [
  {
    step: '01',
    title: 'Structure',
    description: 'Entity formation, compliance setup, legal infrastructure.',
  },
  {
    step: '02',
    title: 'Implement',
    description: 'Systems, operations, and processes installed and running.',
  },
  {
    step: '03',
    title: 'Optimize',
    description: 'Performance audits, cost reduction, efficiency gains.',
  },
  {
    step: '04',
    title: 'Scale',
    description: 'Growth execution, market expansion, advanced systems.',
  },
];

export default function LifecycleSection(): JSX.Element {
  return (
    <section className={styles.wrapper}>
      <div className={styles.content}>
        <p className={styles.label}>OUR PROCESS</p>
        <h2 className={styles.heading}>Built for Every Stage of Business.</h2>
        <div className={styles.grid}>
          {pillars.map(({ step, title, description }) => (
            <article key={step} className={styles.card}>
              <span className={styles.step}>{step}</span>
              <h3 className={styles.title}>{title}</h3>
              <p className={styles.description}>{description}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
```

3. Data fetching  
None; `pillars` array is hard-coded static content.

4. Edge cases  
• SSR/CSR identical rendering ensured by CSS modules (no runtime logic).  
• Zero dynamic props/state—component always renders correctly regardless of parent.

5. Strict constraints (what it must NOT do)  
• Must NOT import or use Mantine components, styles, or tokens.  
• Must NOT import or use icons from @tabler/icons-react.  
• Must NOT fetch from any API or poll any endpoint.