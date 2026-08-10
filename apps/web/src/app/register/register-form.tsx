'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { createBrowserApiClient } from '@/lib/browser-api-client';

export function RegisterForm() {
  const router = useRouter();
  const [step, setStep] = useState<'details' | 'otp'>('details');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [mobile, setMobile] = useState('');
  const [otp, setOtp] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function createAccount(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setInfo(null);
    setPending(true);
    try {
      const api = createBrowserApiClient();
      const res = await api.register({ email: email.trim(), name: name.trim(), mobile: mobile.trim() });
      setInfo(res.message ?? (res.requiresOTP ? 'OTP sent to your email.' : 'Check your email for the code.'));
      setStep('otp');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed.');
    } finally {
      setPending(false);
    }
  }

  async function verify(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      const api = createBrowserApiClient();
      await api.verifyOtp(email.trim(), otp.trim());
      router.replace('/dashboard/');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Verification failed.');
    } finally {
      setPending(false);
    }
  }

  if (step === 'otp') {
    return (
      <form onSubmit={verify} className="flex flex-col gap-6 w-full">
        {error && (
          <div role="alert" className="text-white bg-red-600 brutalist-border p-3 text-sm font-bold uppercase tracking-widest text-center shadow-[4px_4px_0px_#111]">
            {error}
          </div>
        )}
        {info && (
          <div role="status" className="text-black bg-green-100 brutalist-border p-3 text-sm font-bold uppercase tracking-widest text-center">
            {info}
          </div>
        )}
        <div className="text-sm text-gray-600 -mb-2">
          One-time code sent to <span className="font-bold text-black">{email}</span>
        </div>
        <label className="flex flex-col gap-2">
          <span className="text-sm font-black uppercase tracking-widest text-black">OTP Code</span>
          <input
            name="otp"
            type="text"
            inputMode="numeric"
            maxLength={8}
            required
            autoFocus
            value={otp}
            onChange={(e) => setOtp(e.target.value)}
            className="brutalist-border px-4 py-3 bg-white text-black focus:outline-none focus:ring-4 focus:ring-gray-200 transition-all font-medium"
          />
        </label>
        <button type="submit" disabled={pending} className="btn-brutalist w-full py-4 text-base mt-2">
          {pending ? 'Verifying…' : 'Verify & Sign in'}
        </button>
        <button
          type="button"
          onClick={() => {
            setStep('details');
            setError(null);
            setInfo(null);
            setOtp('');
          }}
          className="text-xs font-bold uppercase tracking-widest text-gray-500 underline"
        >
          ← Edit details
        </button>
      </form>
    );
  }

  return (
    <form onSubmit={createAccount} className="flex flex-col gap-6 w-full">
      {error && (
        <div role="alert" className="text-white bg-red-600 brutalist-border p-3 text-sm font-bold uppercase tracking-widest text-center shadow-[4px_4px_0px_#111]">
          {error}
        </div>
      )}
      <label className="flex flex-col gap-2">
        <span className="text-sm font-black uppercase tracking-widest text-black">Full Name</span>
        <input
          name="name"
          type="text"
          required
          autoComplete="name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="brutalist-border px-4 py-3 bg-white text-black focus:outline-none focus:ring-4 focus:ring-gray-200 transition-all font-medium"
        />
      </label>
      <label className="flex flex-col gap-2">
        <span className="text-sm font-black uppercase tracking-widest text-black">Email</span>
        <input
          name="email"
          type="email"
          required
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="brutalist-border px-4 py-3 bg-white text-black focus:outline-none focus:ring-4 focus:ring-gray-200 transition-all font-medium"
        />
      </label>
      <label className="flex flex-col gap-2">
        <span className="text-sm font-black uppercase tracking-widest text-black">
          Mobile <span className="text-gray-400 normal-case">(optional)</span>
        </span>
        <input
          name="mobile"
          type="tel"
          autoComplete="tel"
          value={mobile}
          onChange={(e) => setMobile(e.target.value)}
          className="brutalist-border px-4 py-3 bg-white text-black focus:outline-none focus:ring-4 focus:ring-gray-200 transition-all font-medium"
        />
      </label>
      <button type="submit" disabled={pending} className="btn-brutalist w-full py-4 text-base mt-2">
        {pending ? 'Creating account…' : 'Create account & send code'}
      </button>
      <p className="text-center text-xs font-bold uppercase tracking-widest text-gray-500">
        Already registered?{' '}
        <Link href="/login/" className="underline">
          Sign in
        </Link>
      </p>
    </form>
  );
}