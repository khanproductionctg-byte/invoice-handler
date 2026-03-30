"use client"

import { useEffect, useState } from 'react'
import { useAuth } from "@clerk/nextjs"
import { api } from "@/lib/api"
import { Sidebar } from "@/components/sidebar"

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const { getToken, isLoaded } = useAuth()
  const [ready, setReady] = useState(false)

  useEffect(() => {
    const setupAuth = async () => {
      if (isLoaded) {
        try {
          const token = await getToken()
          if (token) {
            api.setToken(token)
          }
        } catch (error) {
          console.error('Failed to get auth token:', error)
        }
        setReady(true)
      }
    }
    setupAuth()
  }, [getToken, isLoaded])

  if (!ready) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900"></div>
      </div>
    )
  }

  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex-1 overflow-y-auto bg-gray-50">
        <div className="container mx-auto p-6">{children}</div>
      </main>
    </div>
  )
}
