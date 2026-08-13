import { RegisterForm } from './register-form';

export const metadata = { title: 'Create account — Digital Twin FM' };

export default function RegisterPage() {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center p-6 gap-8 bg-[#f4f4f0]">
      <header className="text-center animate-fade-in-up">
        <div className="flex justify-center mb-6">
          <div className="h-16 w-16 flex items-center justify-center font-black text-2xl brutalist-border bg-white text-black shadow-[4px_4px_0px_#111]">
            DT
          </div>
        </div>
        <h1 className="text-4xl md:text-6xl font-black uppercase tracking-tighter text-black">Digital Twin FM</h1>
        <p className="text-sm font-bold uppercase tracking-widest text-gray-500 mt-4">Create your account // OTP via email</p>
      </header>
      <div className="w-full max-w-md bg-white brutalist-border shadow-[8px_8px_0px_#111] p-8 animate-fade-in-up delay-1">
        <RegisterForm />
      </div>
    </main>
  );
}