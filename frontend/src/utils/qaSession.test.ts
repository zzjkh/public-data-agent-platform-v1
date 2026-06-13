import { beforeEach, describe, expect, it } from 'vitest';

import type { QaResponse } from '../api/qa';
import {
  clearQaPageSession,
  loadQaPageSession,
  qaSessionKey,
  saveQaPageSession,
} from './qaSession';

const response: QaResponse = {
  trace_id: 'trace-1',
  route_type: 'DATA_QA',
  answer: '北京市 2024 年常住人口为 2183.2 万人。',
  citations: [],
  sql: null,
  chart: null,
  request_id: 'request-1',
};

describe('qaSession', () => {
  beforeEach(() => sessionStorage.clear());

  it('persists sessions per user and clears them explicitly', () => {
    saveQaPageSession('admin', '北京市人口是多少？', response);

    expect(loadQaPageSession('admin')).toMatchObject({
      question: '北京市人口是多少？',
      response,
    });
    expect(loadQaPageSession('demo')).toBeNull();

    clearQaPageSession('admin');
    expect(loadQaPageSession('admin')).toBeNull();
  });

  it('persists a draft before a response exists', () => {
    saveQaPageSession('admin', '还没有提交的问题', null);

    expect(loadQaPageSession('admin')).toMatchObject({
      question: '还没有提交的问题',
      response: null,
    });
  });

  it('removes invalid stored payloads', () => {
    sessionStorage.setItem(qaSessionKey('admin'), '{"question": 123}');

    expect(loadQaPageSession('admin')).toBeNull();
    expect(sessionStorage.getItem(qaSessionKey('admin'))).toBeNull();
  });
});
