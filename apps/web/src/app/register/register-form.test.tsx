import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { RegisterForm } from './register-form';

const routerMock = { push: jest.fn(), replace: jest.fn(), refresh: jest.fn(), prefetch: jest.fn(), back: jest.fn(), forward: jest.fn() };

jest.mock('next/navigation', () => ({
  useRouter: () => routerMock,
}));

const register = jest.fn();
const verifyOtp = jest.fn();

jest.mock('@/lib/browser-api-client', () => ({
  createBrowserApiClient: () => ({ register, verifyOtp }),
}));

describe('RegisterForm (serverless OTP)', () => {
  beforeEach(() => {
    register.mockReset();
    verifyOtp.mockReset();
  });

  it('starts on the details step', () => {
    render(<RegisterForm />);
    expect(screen.getByLabelText(/full name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /create account & send code/i })).toBeInTheDocument();
  });

  it('registers with name, email and mobile then moves to the OTP step', async () => {
    register.mockResolvedValue({ requiresOTP: true, message: 'OTP sent to your email.' });
    render(<RegisterForm />);
    fireEvent.change(screen.getByLabelText(/full name/i), { target: { value: 'Akshay Kumar' } });
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'akshay@dtfm.test' } });
    fireEvent.change(screen.getByLabelText(/mobile/i), { target: { value: '+919876543210' } });
    fireEvent.click(screen.getByRole('button', { name: /create account & send code/i }));
    await waitFor(() => {
      expect(register).toHaveBeenCalledWith({
        email: 'akshay@dtfm.test',
        name: 'Akshay Kumar',
        mobile: '+919876543210',
      });
      expect(screen.getByLabelText(/otp code/i)).toBeInTheDocument();
    });
  });

  it('verifies the OTP and completes sign-in', async () => {
    register.mockResolvedValue({ requiresOTP: true });
    verifyOtp.mockResolvedValue({ token: 't', email: 'akshay@dtfm.test' });
    render(<RegisterForm />);
    fireEvent.change(screen.getByLabelText(/full name/i), { target: { value: 'Akshay Kumar' } });
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'akshay@dtfm.test' } });
    fireEvent.click(screen.getByRole('button', { name: /create account & send code/i }));
    await waitFor(() => expect(screen.getByLabelText(/otp code/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/otp code/i), { target: { value: '654321' } });
    fireEvent.click(screen.getByRole('button', { name: /verify & sign in/i }));
    await waitFor(() => {
      expect(verifyOtp).toHaveBeenCalledWith('akshay@dtfm.test', '654321');
      expect(routerMock.replace).toHaveBeenCalledWith('/dashboard/');
    });
  });

  it('shows an error when registration fails', async () => {
    register.mockRejectedValue(new Error('Email already registered'));
    render(<RegisterForm />);
    fireEvent.change(screen.getByLabelText(/full name/i), { target: { value: 'Akshay Kumar' } });
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'taken@dtfm.test' } });
    fireEvent.click(screen.getByRole('button', { name: /create account & send code/i }));
    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toMatch(/Email already registered/);
    });
  });
});