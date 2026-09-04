import React from 'react';
import { FluidCanvas } from './components/FluidCanvas';
import './App.css';

export const App: React.FC = () => {
  return (
    <div className="eepy-container">
      {/* Dynamic fluid background + floating Zzz particles everywhere */}
      <FluidCanvas />

      {/* ONLY "eepy" in big JetBrains Mono */}
      <main className="eepy-center">
        <h1 className="eepy-text font-mono" data-text="eepy">
          eepy
        </h1>
      </main>
    </div>
  );
};

export default App;
