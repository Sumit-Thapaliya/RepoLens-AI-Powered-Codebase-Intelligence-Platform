import { Router } from 'express';
import { PrismaClient } from '@prisma/client';
import { verifyPassword, createToken } from '../services/authService';
import { UserRepository } from '../repositories/userRepository';

const router = Router();
const prisma = new PrismaClient();

export interface LoginPayload {
  email: string;
  password: string;
}

export async function loginHandler(req, res) {
  const { email, password } = req.body;
  const user = await prisma.user.findUnique({ where: { email } });
  if (!user || !(await verifyPassword(password, user.passwordHash))) {
    return res.status(401).json({ error: 'Invalid credentials' });
  }
  const token = createToken(user);
  return res.json({ token });
}

router.post('/api/login', requireAuth, loginHandler);

export default router;
