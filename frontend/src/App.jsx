import { useState } from 'react'
import './App.css'

function App() {
  return (
    <div className = "dashboard">
      <header className = "header">
        <h1 className = "logo">
          <span className = "logo-blue">Queue</span>Flow
        </h1>
        <p className='subtitle'> Distributed Task Queue Dashboard</p>
      </header>

      <main className = "content">
        <p>Dashboard content will go here</p>
      </main>
    </div>
  )
}
 

export default App
