import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { LoginForm } from './login-form';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), refresh: jest.fn(), prefetch: jest.fn(), back: jest.fn(), forward: jest.fn() }),
}));

const requestOtp = jest.fn();
const verifyOtp = jest.fn();
const routerMock = { push: jest.fn(), replace: jest.fn(), refresh: jest.fn(), prefetch: jest.fn(), back: jest.fn(), forward: jest.fn() };

jest.mock('next/navigation', () => ({
  useRouter: () => routerMock,
}));

jest.mock('@/lib/browser-api-client', () => ({
  createBrowserApiClient: () => ({ requestOtp, verifyOtp }),
}));

describe('LoginForm (serverless OTP)', () => {
  beforeEach(() => {
    requestOtp.mockReset();
    verifyOtp.mockReset();
  });

  it('starts on the email step', () => {
    render(<LoginForm />);
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /send code/i })).toBeInTheDocument();
  });

  it('moves to the OTP step after requesting a code', async () => {
    requestOtp.mockResolvedValue({ requiresOTP: true, message: 'OTP sent to your email.' });
    render(<LoginForm />);
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'user@dtfm.test' } });
    fireEvent.click(screen.getByRole('button', { name: /send code/i }));
    await waitFor(() => {
      expect(screen.getByText(/one-time code sent/i)).toBeInTheDocument();
    });
    expect(screen.getByLabelText(/otp code/i)).toBeInTheDocument();
  });

  it('verifies the OTP and completes sign-in', async () => {
    requestOtp.mockResolvedValue({ requiresOTP: true });
    verifyOtp.mockResolvedValue({ token: 't', email: 'user@dtfm.test' });

    render(<LoginForm />);
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'user@dtfm.test' } });
    fireEvent.click(screen.getByRole('button', { name: /send code/i }));
    await waitFor(() => expect(screen.getByLabelText(/otp code/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/otp code/i), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: /verify & sign in/i }));
    await waitFor(() => {
      expect(verifyOtp).toHaveBeenCalledWith('user@dtfm.test', '123456');
      expect(routerMock.replace).toHaveBeenCalledWith('/dashboard/');
    });
  });

  it('shows an error when the OTP is wrong', async () => {
    requestOtp.mockResolvedValue({ requiresOTP: true });
    verifyOtp.mockRejectedValue(new Error('Invalid OTP or expired code'));
    render(<LoginForm />);
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'user@dtfm.test' } });
    fireEvent.click(screen.getByRole('button', { name: /send code/i }));
    await waitFor(() => expect(screen.getByLabelText(/otp code/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/otp code/i), { target: { value: '000000' } });
    fireEvent.click(screen.getByRole('button', { name: /verify & sign in/i }));
    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toMatch(/Invalid OTP/);
    });
  });
});