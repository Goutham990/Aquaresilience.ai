import './globals.css';
import type { Metadata } from 'next';
export const metadata:Metadata={title:'AquaResilience AI | Response Command',description:'Live evidence-based coastal relief routing'};
export default function RootLayout({children}:{children:React.ReactNode}){
  return <html lang="en"><body>{children}</body></html>;
}
